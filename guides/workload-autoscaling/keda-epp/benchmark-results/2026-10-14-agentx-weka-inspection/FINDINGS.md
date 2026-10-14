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

## Result (two runs, reproduced)
| Metric | Run 1 | Run 2 (with EPP signal trace) |
|--------|-------|------|
| Requests | 134: **67 ok / 67 failed (50%)** | 141: **72 ok / 69 failed (49%)** |
| Failure cause | **100% "400 - Context Window"** | **100% "400 - Context Window"** |
| Successful prompt tokens | mean 10,728 / max 39,753 | similar |
| Successful TTFT | mean 7.82s / p95 12.85s | mean 1.22s / p95 2.79s |
| Autoscaler | held at 1 replica | held at 1 replica |

EPP running-signal trace (run 2, 5s sampling, 78 samples): nonzero only **12%** of samples, exceeded the
running=16 threshold in exactly **1 sample (~5s)**, peak **50**, mean 1.2. Longest consecutive
above-threshold stretch = **5s** vs the **300s** scaleUp window. So the signal is not dead - it spikes -
but the agentic load is **bursty and never sustains**, and the 300s window correctly absorbs the transient.

Exact failure message (verbatim from the report):
> "This model's maximum context length is 40960 tokens. However, you requested 301 output tokens and
> your prompt contains at least 40660 input tokens, for a total of at least 40961 tokens."

Exact failure message (verbatim from the report):
> "This model's maximum context length is 40960 tokens. However, you requested 301 output tokens and
> your prompt contains at least 40660 input tokens, for a total of at least 40961 tokens."

## Findings (empirically validated, not argued)
1. **AgentX does not fit Qwen3-32B.** Half the requests hard-fail with 400 context-overflow. The raw
   traces reach ~1.3M input tokens (the harness logged `1306158 > 131072`); even after the harness caps
   context toward ~40K, ~half still tip just over the 40,960 ceiling. Running the real AgentX workload
   needs a long-context model/stack (e.g. the GLM-5.2 guide runs it at 142K-10M context).
2. **The queue/count signal + 300s window can't react to bursty agentic load.** The pool held at 1
   replica both runs. The EPP running signal DID spike (to 50), but only transiently: above the
   running=16 threshold for ~5s total out of the whole run, and nonzero only 12% of samples. Against a
   300s stabilization window, these sub-10s bursts are (correctly) absorbed - so the pool never scales.
   The agentic session-replay pattern is spiky (requests fire, ~half 400 instantly, brief concurrency
   bursts) rather than the sustained ramp the count-signal + window are tuned for. Also, a count target
   (running=16) does not reflect the token/prefill work an agentic request carries. Both point to the
   token-aware signal (tokens of outstanding work) for agentic/long-context load.

## Caveats
- This is an INSPECTION at native session pacing (64 sessions), not a tuned autoscaled-vs-static protocol.
- Run 1's EPP `request_running` trace was not captured (the scrape helper pod had expired); run 2 fixed
  that and captured it (data/rec-weka.csv) - the scaling conclusion is confirmed by both `ready=1` and
  the EPP trace.
- Reproducible artifacts in `data/` (BRV0.2 stage + session reports, summary with the served/400 split +
  verbatim failure messages, run metadata, and the run-2 EPP signal trace rec-weka.csv). The run also
  auto-deployed an in-namespace prism instance with this data.

## So what
Confirms the team's assumptions: (a) AgentX belongs on a long-context stack, not Qwen3-32B; (b) the
keda+epp queue/count path is the wrong autoscaling signal for agentic/prefill-heavy load - token-aware
(tokens of outstanding work) is the right dimension. See the keda-epp-token-aware guide.
