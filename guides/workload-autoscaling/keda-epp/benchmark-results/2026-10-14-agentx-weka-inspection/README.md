# AgentX (weka cc-traces) inspection - keda+epp queue path

Internal inspection shared via this branch, not published guide content.

**Question:** what does the shipped keda+epp QUEUE-path autoscaler do under a real agentic workload
(SemiAnalysis cc-traces / "AgentX") on the Qwen3-32B optimized-baseline stack?

**Headline:** it doesn't fit and it doesn't scale.
- **50% of requests hard-fail** with `400 - Context Window` - AgentX prompts (up to ~1.3M tokens; ~40,660
  after the harness caps) exceed Qwen3-32B's `max_model_len = 40,960`.
- **The autoscaler never scaled** (held at 1 replica) - the queue/count signal doesn't reflect agentic
  prefill work.

Takeaway: AgentX needs a long-context model/stack, and agentic/prefill-heavy load wants the **token-aware**
signal, not the queue/count path.

## Contents
- [FINDINGS.md](FINDINGS.md) - full setup, numbers, caveats.
- `data/` - reproducible BRV0.2 stage + session reports, `summary_lifecycle_metrics.json` (the 67/67
  split + verbatim 400 messages), and run metadata.
