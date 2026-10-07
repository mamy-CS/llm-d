# Benchmarking the keda-epp queue-signal autoscaler

How to measure the queue-signal path from [../README.md](../README.md): drive a
staged load ramp against a pool deployed with `SIGNAL=queue`, and record whether
the autoscaler adds replicas as unmet demand appears and removes them as it
drains, at what replica cost relative to a static pool sized for peak.

This is the reusable harness. `queue-ramp-config.yml` is the load profile (an
ordinary [inference-perf](https://github.com/kubernetes-sigs/inference-perf)
config), and `plot_run.py` fetches the scaling series from Prometheus and plots
the run. A committed run's output lands in
[`../benchmark-results/`](../benchmark-results/).

> [!NOTE]
> Scope: this covers the **queue** signal only. The saturation signal is
> experimental (no nightly coverage yet) and is not benchmarked here. See
> [Scaling signals](../../../../docs/architecture/advanced/autoscaling/keda-epp.md#scaling-signals)
> for the distinction.

## What this measures

The queue signal scales on two triggers raced against each other: EPP
flow-control queue size (`AverageValue` target `1` per replica) and running
requests (`AverageValue` target `16` per replica). Which one drives scale-up
depends on the load regime, and that is the thing to observe:

- Below pool saturation, flow control dispatches everything, the queue stays at
  zero, and the **running-requests** trigger is the signal that moves.
- Once saturation reaches its ceiling, unmet demand surfaces as **queue size**,
  and the queue trigger (low threshold, `1`) drives scale-up promptly.

A good benchmark ramp crosses that boundary so both regimes appear in one run.
See
[Flow Control On vs. Off](../../../../docs/architecture/advanced/autoscaling/keda-epp.md#flow-control-on-vs-off)
for why.

## Environment

Fill this in for your run. The values below are the guide defaults, not a
published result.

| | |
|---|---|
| Cluster | NVIDIA H100 80 GB, 2 GPUs per replica (TP=2); (fill: provider, node count) |
| Model | Qwen/Qwen3-32B, vLLM, TP=2 (guide default) |
| Gateway | llm-d EPP per the [optimized-baseline guide](https://github.com/llm-d/llm-d/tree/main/guides/optimized-baseline), flow control enabled |
| Signal | queue (`SIGNAL=queue`) |
| Thresholds | queue size `1` / replica, running `16` / replica (`AverageValue`) |
| Bounds | 1-8 replicas (`minReplicaCount` / `maxReplicaCount`) |
| Overshoot | windows (300 s scaleUp/scaleDown stabilization) or guard |
| Prometheus | EPP scraped at the stack default; `pollingInterval` 15 s |

Pod cold-start dominates how the ramp looks. A replica can take minutes to load
the model and become Ready (about 240 s for Qwen3-8B at TP1 on our hardware),
and the 300 s stabilization window is sized to that. A larger model or a smaller
GPU saturates at lower load, so the ramp that crosses the queue boundary differs
per deployment; tune it (see below).

## Workload

`queue-ramp-config.yml` runs a constant-rate staged ramp that climbs past the
pool's serving capacity and then drains:

```
4 rps (300 s) -> 8 (300) -> 12 (300) -> 16 (300) -> 8 (300) -> 2 (300)
```

Random data, streaming completions, roughly 2000 input / 1000 output tokens per
request. Latency is read from the inference-perf client report and the scaling
behavior is read from Prometheus.

**Tuning the ramp is required, not optional.** The rates above are a starting
point for Qwen3-32B at TP=2. If `llm_d_epp_flow_control_queue_size` never goes
non-zero during the run, the ramp never saturated a replica and you only
exercised the running trigger: raise the peak `rate` and the output-token count
until the queue builds. A smaller model or larger GPU needs a higher peak; a
larger model or smaller GPU needs less. This is the same load sensitivity the
guide's guard section calls out.

## Running the workload

The load is driven by
[`llmdbenchmark`](https://github.com/llm-d/llm-d-benchmark), the supported
standard CLI for llm-d performance benchmarking, using its `inference-perf`
harness. The profile in this folder is an ordinary inference-perf config passed
to `-w/--workload`, which accepts either a profile name from the harness catalog
(`workload/profiles/inference-perf/`) or a full path to a local file like ours.

> [!NOTE]
> Flags below are for the current [`docs/run.md`](https://github.com/llm-d/llm-d-benchmark/blob/main/docs/run.md);
> the CLI is young and moves. Confirm against your installed version with
> `llmdbenchmark run --help` before copying commands.

The benchmark repo also ships per-guide profiles in that catalog (for example
`guide_optimized-baseline_1`, a Poisson ramp against the baseline stack this
guide builds on). Those climb to ~60 rps, which pegs a 1-8 replica pool at the
ceiling; our local ramp is tuned to the autoscaler's thresholds instead. The
canonical home for a tuned `guide_keda-epp` profile is that catalog - promoting
this ramp there is follow-up work.

First deploy the queue-signal path and confirm it is scaling, following
[../README.md](../README.md) through **Verify Scale-Up**. Then install the CLI
(clones the repo into `./llm-d-benchmark/` with a venv):

```bash
curl -sSL https://raw.githubusercontent.com/llm-d/llm-d-benchmark/main/install.sh | bash
cd llm-d-benchmark
source .venv/bin/activate
```

Resolve the endpoint of the already-deployed guide stack and point at this
folder. We drive the ramp against the running guide stack (`--endpoint-url`)
rather than having the harness stand one up:

```bash
export NAMESPACE=llm-d-optimized-baseline
export ENDPOINT_URL="http://$(kubectl get service optimized-baseline-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')"
export TEMPLATES_DIR=<path-to-llm-d-repo>/guides/workload-autoscaling/keda-epp/benchmark-templates
```

Run the ramp. `--spec` (a global flag, before `run`) selects the scenario; pick
the one matching your deployment from the repo's `setup/` examples (the
[optimized-baseline example](https://github.com/llm-d/llm-d-benchmark/tree/main/setup)
matches this guide's stack):

```bash
llmdbenchmark \
    --spec         examples/optimized-baseline \
    run \
    --endpoint-url "${ENDPOINT_URL}" \
    --models       Qwen/Qwen3-32B \
    --namespace    "${NAMESPACE}" \
    --harness      inference-perf \
    --workload     "${TEMPLATES_DIR}/queue-ramp-config.yml"
```

The `REPLACE_ENV_LLMDBENCH_*` tokens in the profile are substituted at run time
from the `--models` / `--endpoint-url` flags, so no `envsubst` step is needed.

Latency and throughput come from the universal Benchmark Report the run emits
(`benchmark_report_v*.yaml`); enable the local analysis pass with
`LLMDBENCH_RUN_EXPERIMENT_ANALYZE_LOCALLY=1`, or render it with
[llm-d-prism](https://github.com/llm-d/llm-d-benchmark). `plot_run.py` below adds
only the autoscaling-specific overlay (the scaling signals and replica count),
which the standard report does not chart.

> [!NOTE]
> Use a harness image `>= v0.7.0` (the CLI default). Older images bundle a
> pre-fix inference-perf whose workers share one RNG stream, so random-data
> prompts are duplicated across workers; the resulting prefix-cache hits flatten
> latency and invalidate the run.

### Run protocol

The two rows in [Results](#results) come from the **same ramp run twice**:

1. **Static baseline** - pin the pool at the peak size (set `minReplicaCount` =
   `maxReplicaCount` = the peak, or suspend the ScaledObject and scale the
   Deployment by hand), then run the ramp. This is the cost-for-peak reference.
2. **keda-epp queue loop** - restore the autoscaler (min 1 / max 8) and run the
   identical ramp.

One ramp is ~30 min (six 5-minute stages); the autoscaler run needs another
~5-10 min of tail so the pool drains back to the floor, so budget **~30-45 min of
measured window per run** plus deploy and first-replica cold start.

Tune before you measure: a first pass may show `llm_d_epp_flow_control_queue_size`
never leaving zero (see [Workload](#workload)) - re-tune the peak rate and rerun
until the queue builds, then capture the two measured runs. Repeat each measured
run and average if GPU time allows (the wva guide averages three); a single clean
run of each is the floor.

## Plotting the run

`plot_run.py` fetches the series from Prometheus and plots, in five stacked
panels: the two scaling signals against their thresholds (queue size vs 1,
running vs 16), pool saturation vs 1.0, replicas (provisioned, ready, and the
desired count reconstructed from the two triggers), and TTFT p50/p90 read right
next to replicas - so the replica saving and the latency it held show in one
image. It needs matplotlib (`pip install -r requirements.txt`) and a Prometheus
reachable at `PROM_URL`. Set `TTFT_REF` (seconds) to draw a visual reference line
on the TTFT panel; it is a visual guide only, not a scored threshold.

Make Prometheus reachable from your machine, then run the script with the run's
start time (UTC):

```bash
# Generic k8s: bundled kube-prometheus-stack
kubectl -n llm-d-monitoring port-forward svc/llmd-kube-prometheus-stack-prometheus 9090:9090 &
# OpenShift: Thanos Querier instead
#   kubectl -n openshift-monitoring port-forward svc/thanos-querier 9090:9091

export PROM_URL=http://localhost:9090
export RUN_START=2026-01-01T00:00:00Z   # when you launched the ramp
pip install -r requirements.txt
python plot_run.py
```

It writes `queue-run-overview.png` into `../benchmark-results/` and prints the
time-averaged replica count (the cost number).

NOTE: two of the series only appear under load, so expect them flat or empty
early in the run - this is correct, not a plotting bug.
`llm_d_epp_flow_control_queue_size` is lazily created: EPP emits it only once
flow control actually queues, so it is absent at idle and the queue panel stays
at zero until the ramp saturates a replica (if it never leaves zero, the ramp
never saturated - raise the load). The TTFT panel needs vLLM's
`vllm:time_to_first_token_seconds_bucket` scraped from the decode pods into
Prometheus; confirm the guide namespace's vLLM pods are a scrape target (on
OpenShift, user-workload monitoring) or the panel will be empty.

Override the deployment/namespace/model defaults with the matching environment
variables (`DEPLOY`, `NS_DEPLOY`, `EPP_SERVICE`, `MODEL`) if you benchmarked a
different stack.

## What good looks like

- The pool holds at the floor (1) while load is light, with queue at zero and
  the running trigger carrying the signal.
- As the ramp climbs past saturation, `llm_d_epp_flow_control_queue_size` goes
  non-zero and the HPA scales up toward the ceiling (8), gated by the 300 s
  scaleUp window (or immediately, under `OVERSHOOT=guard`).
- After the ramp drains, the pool scales back down to the floor once the
  scaleDown window clears.
- Time-averaged replicas over the full run come in below a static pool sized for
  peak; that gap is the saving the autoscaler buys.
- TTFT (from the inference-perf report) holds within an acceptable band through
  the ramp - the replica saving should not come at a latency cliff. TTFT is the
  quality metric that gates the saving; TPOT and throughput are secondary. Report
  the numbers so the cost saving is read against the quality it bought.

## Results

Not yet published. Commit a run's `queue-run-overview.png` to
[`../benchmark-results/`](../benchmark-results/) and fill the table below.

The baseline is **static allocation**: a fixed pool sized to meet peak demand,
provisioned for the whole run. The autoscaler instead tracks demand, so its
time-averaged replicas sit below that peak - the gap between average and peak is
the cost the autoscaler saves. **TTFT is the quality metric of record**: the
saving only counts if TTFT holds while replicas drop. TPOT and throughput are
secondary context. The queue signal drives scaling off queue depth and running
requests, not a latency objective, so the latency columns are reported, not graded.

| Configuration | Avg replicas | Peak replicas | TTFT p50 | TTFT p90 | TPOT p90 | Throughput (tok/s) | Errors |
|---|---|---|---|---|---|---|---|
| Static pool sized for peak | (= peak) | (= peak) | | | | | |
| keda-epp queue loop (this guide) | | | | | | | |

Replica counts come from `plot_run.py` (the cost number it prints); the latency
and throughput columns come from the inference-perf client report / Benchmark
Report. Commit `queue-run-overview.png` for the scaling-signal view.
