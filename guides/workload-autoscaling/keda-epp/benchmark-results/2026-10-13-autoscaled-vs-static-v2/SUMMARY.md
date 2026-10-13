# Summary - keda-epp queue autoscaling vs static (v2)

**One line:** keda-epp queue autoscaling saves ~43% of GPU-minutes vs static-at-peak; the default 300s
scaleUp window makes that cost 66% goodput, a tuned window makes it 94% (near static's 97%) for free.

## Setup
- Qwen3-32B, TP=2, 2x H100-80GB, vLLM, monolithic decode (not P/D). EPP flow-control on.
- Weights pre-staged (PVC HF cache) -> load-bound cold start ~186s (measured x3: 185/186/188s).
- Autoscaler: keda-epp queue path, triggers queue_size (target 1) + running (target 16), min1/max8.
- Load: open-loop Poisson ramp, low -> peak 2.0 req/s -> low (~43 min), random 2048/2048 tokens.
- Goodput SLO: TTFT<=2s AND TPOT<=50ms (llm-d-benchmark autoscaling default, PR #2022). Harness 0.8.0.
- Calibrated so the pool settles at a mid-range desired ~5 at peak (not pinned at max).

## Result
| Arm | Goodput | Fail | GPU replica-min | peak replicas |
|-----|--------:|-----:|----------------:|--------------:|
| Static (pinned 5) | 96.7% | 0 | 220 | 5 fixed |
| Autoscaled, 300s window (default) | 66.0% | 269 | 126 (-43%) | 1->8->5 |
| Autoscaled, tuned window | 94.3% | 18 | 126 (-43%) | 1->5-6 |

## Why
- Savings come from running 1 replica at low load instead of 5.
- The 300s window held desired=1 for ~4-5 min while one replica hit 10-17x saturation (TTFT p99 92s),
  then overshot to max 8. That delay is the goodput killer.
- Tuned window (window 0 + Pods/1 per 180s = one pod at a time, paced to the 186s cold start) scales up
  immediately and gradually: peak saturation ~2.2, no overshoot, goodput back to 94%.

## Takeaway
The bottleneck is the scaleUp window default, not autoscaling. Immediate + rate-limited scale-up keeps
the GPU savings and recovers the goodput. Pre-staging + warm-pool/FMA shrink the remaining gap.

See FINDINGS.md for detail, plots/ for the figures, and the per-arm folders for the raw BRV0.2 reports.
