# keda-epp queue-signal benchmark results

> These are internal findings shared via
> the branch, NOT published guide content.

Methodology + reusable harness: [`../benchmark-templates/`](../benchmark-templates/)
([BENCHMARK.md](../benchmark-templates/BENCHMARK.md)).

## Runs

### [2026-10-14-agentx-weka-inspection/](2026-10-14-agentx-weka-inspection/)
Inspection: the SemiAnalysis agentic trace ("AgentX" / `weka_traces` cc-traces) against the keda+epp
queue path on Qwen3-32B. Result: 50% of requests 400 (context overflow - prompts exceed the 40,960
ceiling) and the autoscaler never scaled (held at 1 replica). AgentX needs a long-context stack, and
agentic load wants the token-aware signal, not queue/count. See
[FINDINGS.md](2026-10-14-agentx-weka-inspection/FINDINGS.md).

### [2026-10-13-autoscaled-vs-static-v2/](2026-10-13-autoscaled-vs-static-v2/)
Qwen3-32B, TP=2, 2x H100-80GB, vLLM, monolithic. Pre-staged weights, calibrated mid-range operating
point, open-loop Poisson ramp, goodput-gated (TTFT<=2s, TPOT<=50ms). Three arms: static (pinned 5),
autoscaled with the as-shipped 300s scaleUp window, and autoscaled with a tuned scale-up (Pods/1 @180s).

Start here:
- [SUMMARY.md](2026-10-13-autoscaled-vs-static-v2/SUMMARY.md) - one page.
- [FINDINGS.md](2026-10-13-autoscaled-vs-static-v2/FINDINGS.md) - decision-grade.
- [plots/](2026-10-13-autoscaled-vs-static-v2/plots/) - replicas+saturation over time, goodput-vs-GPU, demand-vs-free-capacity in KV tokens.
- `{static,auto-asshipped,auto-tuned}/` - BRV0.2 reports + summary (goodput); `config/` - the workload.

Headline: queue autoscaling saves ~43% GPU-minutes vs static; the default 300s scaleUp window costs
that as 66% goodput (delayed scale-up -> 1 replica at 10-17x saturation, then overshoot to max), while
a tuned scale-up (immediate + one pod at a time, paced to cold start) gets 94% goodput (vs static 97%) at
the same GPU saving. The scaleUp config (stabilization window + rate policy) is the lever, not autoscaling itself; this run changed both together and does not isolate their individual effects.
