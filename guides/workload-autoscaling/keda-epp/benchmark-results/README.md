# keda-epp queue-signal benchmark results

No run is published yet. The methodology and the reusable harness live in
[`../benchmark-templates/`](../benchmark-templates/) ([BENCHMARK.md](../benchmark-templates/BENCHMARK.md)).

A follow-up will commit a real run here:

- `queue-run-overview.png` - the plot `plot_run.py` emits (queue and running
  signals vs their thresholds, pool saturation, replicas, and TTFT p50/p90 over
  the run, so the replica saving and the latency it held read in one image).
- A short results summary: peak served throughput, time-averaged replicas vs a
  static pool sized for peak, and the latency percentiles from the inference-perf
  client report.
