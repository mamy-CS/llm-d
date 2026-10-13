# keda-epp queue autoscaling vs static - findings (v2, pre-staged, calibrated, goodput-gated)

Written for: the llm-d autoscaling engineers. Internal note shared via this branch, not the user guide.
Model/HW: Qwen3-32B, TP=2, 2x H100-80GB, vLLM, monolithic decode (NOT P/D). EPP flow-control on.

## Bottom line

On a properly configured (weight-pre-staged) deployment, keda-epp queue-path autoscaling saves
**~43% of GPU-minutes** versus running static at peak. Whether that is nearly free or very expensive
depends entirely on **one setting - the scaleUp stabilization window**:

- The **as-shipped 300s window** pays a brutal quality price: **goodput 66%** (vs static's 97%), 269
  failed requests, TTFT p99 **92s**. The window delays scale-up so a single replica drowns, then the
  pool overshoots to max.
- A **tuned window** (scale up immediately, one pod at a time paced to the cold start) delivers the
  **same ~43% GPU saving at 94% goodput** - within ~2 points of static, 18 failures, TTFT p99 14s.

So the problem is not autoscaling; it is the default scaleUp window. Fixing it recovers ~28 points of
goodput at no extra GPU cost.

## The numbers

Same calibrated open-loop Poisson ramp (low -> peak rate 2.0 req/s -> low, ~43 min) on all three arms.
Goodput = fraction of requests meeting TTFT<=2s AND TPOT<=50ms (the llm-d-benchmark autoscaling default,
PR #2022, verified on origin/main). GPU = replica-minutes integrated over the active ramp.

| Arm | Goodput | Failures | TTFT mean / p99 | GPU replica-min | mean replicas | peak replicas |
|-----|--------:|---------:|----------------:|----------------:|--------------:|--------------:|
| Static (pinned 5) | **96.7%** | 0 | 0.17 / 0.34s | 220 | 5.00 | 5 (fixed) |
| Autoscaled, 300s window (as-shipped) | **66.0%** | 269 | 16.1 / 91.6s | 126 (-43%) | 2.9 | 1->**8**->5 |
| Autoscaled, tuned window | **94.3%** | 18 | 0.48 / 13.9s | 126 (-43%) | 2.9 | 1->5-6 |

See plots/replicas_saturation.png (the mechanism) and plots/goodput_vs_gpu.png (the tradeoff).

## 1. Autoscaling saves ~43% of GPU-minutes [PROVEN LIVE]
The ramp needs 5 replicas only at peak; at low load 1 suffices. Static pays for 5 the whole time
(220 replica-min); both autoscaled arms run ~1 at low load and scale for the peak (126 replica-min,
mean 2.9). The saving is real and independent of the window - it comes from not over-provisioning
during low load. (Measured over the active ramp; the idle tail would widen the gap.)

## 2. The as-shipped 300s scaleUp window wrecks goodput [PROVEN LIVE]
At peak onset the 300s stabilization window HELD desired=1 for ~4-5 minutes while a single replica sat
at **10-17x the dispatch-gate saturation** (in-flight 164-209). TTFT collapsed (mean 16s, p99 92s) and
269 requests failed. THEN - because a large backlog had built during the delay - desired slammed
straight to **max (8)**, not the needed 5, before settling back. So the default window gives you the
worst of both: a long quality outage during the delay AND transient over-provisioning after it.
This is the same class of problem behind the earlier overshoot work; here it is quantified end-to-end.

## 3. A tuned window recovers almost all of it, for free [PROVEN LIVE]
Config: scaleUp `stabilizationWindowSeconds: 0` + `policies: [{type: Pods, value: 1, periodSeconds: 180}]`
(one pod at a time, paced to the measured ~186s cold start). The pool starts scaling immediately at
peak onset and climbs 1->2->3->4->5 smoothly; peak saturation tops out at **~2.2 briefly** (vs 17) and
it does **not** overshoot to max. Goodput 94.3% (vs 66%), 18 failures (vs 269), TTFT p99 14s (vs 92s) -
all at the **same 126 replica-min** as the as-shipped arm. The gradual climb let a small backlog push it
to 6 briefly; a minor, self-correcting effect.

## Cold start (context, not the finding)
That cold start hurts scale-up is well known. We pre-staged weights (PVC-backed HF cache; the standard
`guides/recipes/modelserver/components/model-cache` pattern) so the measured cold start is the normal
**load-bound ~186s**, not this deployment's download-bound ~481s (the no-cache path - a separate
deployment gap: the optimized-baseline vLLM modelserver ships emptyDir caches, so weights re-download
on every scale-up; the standard model-cache component fixes it). ~186s is
why "one pod per 180s" is the right pacing: do not
add pod N+1 until pod N can be ready. Warm-pool / FMA would shrink the 186s and make even the tuned
ramp near-instant; out of scope here.

## Method and verification
- Calibration: swept Poisson rate with scaleUp window=0; rate 2.0 req/s settles at desired 5 (running
  ~80 = 5x the running-trigger target 16), rate 3.0 runs away to max. R=2.0 chosen for a mid-range peak.
- Harness: llm-d-benchmark 0.8.0 (>= v0.7.0, so no shared-RNG prefix-cache confound). Confirmed
  prompt_tokens cached=0 in every run - random prompts, no prefix-cache masking.
- Goodput is inference-perf's computed value from summary_lifecycle_metrics.json (the BRV0.2 report
  only echoes the goodput config). Per-arm reports + summaries are in the {static,auto-asshipped,
  auto-tuned}/ folders; the calibrated workload is in config/.
- TPOT was the binding constraint for static (long-tail decodes); TTFT was binding for the autoscaled
  arms (the scale-up lag). TPOT attainment was ~95-97% across all arms.

### Caveats
- Two brackets measured (static vs the two autoscaled configs) at one calibrated operating point; not a
  full rate sweep. Mid-points are interpolated.
- The tuned arm's ~18 failures are a scale-DOWN artifact: when the pool shrank for the low stage, a few
  long in-flight generations were cut (TransferEncodingError). Real, but a scale-down concern, not scale-up.
- Numbers belong in prism / llm-d-autoscaling per the benchmark-numbers policy, not the published guide.

## Recommendation
1. Change the keda-epp queue scaleUp default away from a long stabilization window toward
   **immediate + rate-limited (Pods/1 paced to cold start)**. It recovers ~28 points of goodput at no
   GPU cost on this workload. Validate across token shapes before shipping.
2. Pre-stage weights (the model-cache component) so scale-up is load-bound, and pursue warm-pool/FMA to
   shrink the ~186s further - that is what shrinks the remaining tuned-vs-static gap.
3. The scale-DOWN path should drain in-flight requests before terminating replicas (the 18-failure
   artifact) - separate follow-up.
