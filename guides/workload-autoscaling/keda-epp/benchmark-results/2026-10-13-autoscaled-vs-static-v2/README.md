# keda-epp queue autoscaling vs static (v2)

Internal benchmark shared via this branch, not published guide content.
Qwen3-32B, TP=2, 2x H100-80GB, vLLM, monolithic. Pre-staged weights, calibrated operating point,
open-loop Poisson ramp, goodput-gated (TTFT<=2s, TPOT<=50ms). Three arms: static (pinned 5),
autoscaled as-shipped (300s scaleUp window), autoscaled tuned (Pods/1 @180s).

**Headline:** queue autoscaling saves ~43% GPU-minutes vs static-at-peak. The default 300s scaleUp
window costs that as 66% goodput (delayed scale-up -> 1 replica at 10-17x saturation, then overshoot to
max 8); a tuned scale-up (immediate + one pod at a time, paced to the cold start) gets 94% goodput (vs
static's 97%) at the same GPU saving. The scaleUp config (stabilization window + rate policy) is the lever, not autoscaling itself; this run changed both together and does not isolate their individual effects.

| Arm | Goodput | Failures | GPU replica-min | peak replicas |
|-----|--------:|---------:|----------------:|--------------:|
| Static (pinned 5) | 96.7% | 0 | 220 | 5 fixed |
| Autoscaled, 300s window | 66.0% | 269 | 126 (-43%) | 1->8->5 |
| Autoscaled, tuned scale-up | 94.3% | 18 | 126 (-43%) | 1->5-6 |

## Contents
- [SUMMARY.md](SUMMARY.md) - one page.
- [FINDINGS.md](FINDINGS.md) - decision-grade conclusions + method + caveats.
- [plots/](plots/) - replicas+saturation over time; goodput-vs-GPU tradeoff.
- `static/`, `auto-asshipped/`, `auto-tuned/` - per-arm BRV0.2 stage reports + `summary_lifecycle_metrics.json` (the computed goodput).
- [config/](config/) - the calibrated workload (`queue-ramp-v2.yaml`).
