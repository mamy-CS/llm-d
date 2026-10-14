# AgentX (weka cc-traces) on Qwen3-32B, keda+epp queue path - inspection

Written for: the llm-d autoscaling team. Internal note (not the user guide).
Date: 2026-10-14. Purpose: INSPECT what happens when the SemiAnalysis agentic trace is run against
the shipped keda+epp QUEUE-path autoscaler on the Qwen3-32B optimized-baseline stack.

## Setup (reproducible)
- Workload: `weka_traces` profile (inference-perf `trace_session_replay`, 64 concurrent sessions),
  dataset `semianalysisai/cc-traces-weka-with-subagents-051926` (SemiAnalysis Claude-Code agent traces
  with subagents = the "AgentX" family). Public dataset, no HF token needed.
- Model/stack: Qwen3-32B, TP=2, 2x H100-80GB, vLLM, optimized-baseline, `max_model_len = 40,960`.
- Autoscaler: keda+epp QUEUE path, min1/max8, triggers queue_size (target 1) + running (target 16),
  scaleUp window 300s (as-shipped).
- Harness: llm-d-benchmark `llmdbenchmark` 0.8.0 on current `main` (f0182f9), Python 3.14 venv.

## Result
| Metric | Value |
|--------|-------|
| Requests | 134 total: **67 succeeded / 67 failed (50%)** |
| Failure cause | **100% "400 - Context Window"** - prompt ~40,660 input tokens + output > 40,960 ceiling |
| Successful prompt tokens | mean 10,728 / max 39,753 (just under 40,960) |
| Successful output tokens | mean 196 |
| Successful TTFT | mean 7.82s / p95 12.85s (heavy prefill) |
| Autoscaler behavior | **Never scaled - held at 1 replica the whole run** |

Exact failure message (verbatim from the report):
> "This model's maximum context length is 40960 tokens. However, you requested 301 output tokens and
> your prompt contains at least 40660 input tokens, for a total of at least 40961 tokens."

## Findings (empirically validated, not argued)
1. **AgentX does not fit Qwen3-32B.** Half the requests hard-fail with 400 context-overflow. The raw
   traces reach ~1.3M input tokens (the harness logged `1306158 > 131072`); even after the harness caps
   context toward ~40K, ~half still tip just over the 40,960 ceiling. Running the real AgentX workload
   needs a long-context model/stack (e.g. the GLM-5.2 guide runs it at 142K-10M context).
2. **The queue/count signal is unresponsive to agentic load.** The pool stayed at 1 replica the entire
   run - failures don't register as running requests, and the surviving large-prefill requests didn't
   drive the count past the running=16 / queue=1 thresholds. A count-based signal does not reflect the
   token/prefill work an agentic request carries (one in-context request alone is a large fraction of a
   replica's KV). This points to the token-aware signal for agentic/long-context load.

## Caveats
- This is an INSPECTION at native session pacing (64 sessions), not a tuned autoscaled-vs-static protocol.
- The scaling conclusion is from `kube_deployment ready=1` (reliable); the per-second EPP `request_running`
  trace for this run was not captured (the recorder's metric-scrape helper did not collect it).
- Reproducible artifacts in `data/` (BRV0.2 stage + session reports, summary with the 67/67 + failure
  messages, run metadata). The run also auto-deployed an in-namespace prism instance with this data.

## So what
Confirms the team's assumptions: (a) AgentX belongs on a long-context stack, not Qwen3-32B; (b) the
keda+epp queue/count path is the wrong autoscaling signal for agentic/prefill-heavy load - token-aware
(tokens of outstanding work) is the right dimension. See the keda-epp-token-aware guide.
