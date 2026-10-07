#!/usr/bin/env python3
"""Fetch the keda-epp queue-signal run series from Prometheus, plot it, and
print the cost (time-averaged replicas).

Reachability: queries Prometheus over HTTP at PROM_URL (default
http://localhost:9090). Make it reachable first, e.g.:
  generic k8s:  kubectl -n llm-d-monitoring port-forward svc/llmd-kube-prometheus-stack-prometheus 9090:9090
  OpenShift:    kubectl -n openshift-monitoring port-forward svc/thanos-querier 9090:9091
See BENCHMARK.md.

Panels (one unit each, no dual axes):
  1. Queue size, AverageValue (sum / replicas) vs threshold 1
  2. Running requests, AverageValue (sum / replicas) vs threshold 16
  3. Pool saturation vs 1.0  (the regime line: queue builds once saturation hits it)
  4. Replicas: provisioned + ready + desired (reconstructed from the two triggers)
  5. TTFT p50/p90 (vLLM histogram) - the quality metric of record, read next to
     replicas: the saving holds only if TTFT stays flat as replicas drop. Set
     TTFT_REF to draw a visual reference line (a visual guide only; the queue
     signal is reported, not graded).

Cost: time-averaged provisioned replicas over the window, to compare against a
static pool sized for peak (max replicas).
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# This script lives in benchmark-templates/; output lands in benchmark-results/.
DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "benchmark-results"))

PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090").rstrip("/")
NS_DEPLOY = os.environ.get("NS_DEPLOY", "llm-d-optimized-baseline")
DEPLOY = os.environ.get("DEPLOY", "optimized-baseline-nvidia-gpu-vllm-decode")
EPP_SERVICE = os.environ.get("EPP_SERVICE", "optimized-baseline-epp")
MODEL = os.environ.get("MODEL", "Qwen/Qwen3-32B")
INFERENCE_POOL = os.environ.get("INFERENCE_POOL", "optimized-baseline")

Q_THRESH, R_THRESH = 1.0, 16.0        # AverageValue targets from the ScaledObject
NMIN, NMAX = 1, 8                     # min/max replica bounds from the ScaledObject
# Optional TTFT reference line (seconds). The queue signal is reported, not
# graded, so this is a visual guide only, off unless TTFT_REF is set.
TTFT_REF = float(os.environ["TTFT_REF"]) if os.environ.get("TTFT_REF") else None

BLUE, AQUA, AMBER = "#2a78d6", "#1baf7a", "#d98a1b"
INK, MUTED, SURF, GRIDC = "#0b0b0b", "#52514e", "#fcfcfb", "#e7e6e2"

# Label selector shared by the EPP flow-control / running series.
EPP_SEL = f'namespace="{NS_DEPLOY}",service="{EPP_SERVICE}",model_name="{MODEL}"'
# vLLM exposes TTFT as a histogram; aggregate across the decode pods for the model.
VLLM_SEL = f'namespace="{NS_DEPLOY}",model_name="{MODEL}"'


def promql_range(query, start, end, step=15):
    """query_range against Prometheus (PROM_URL); return [(ts, val)]."""
    q = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": f"{step}s"})
    with urllib.request.urlopen(f"{PROM_URL}/api/v1/query_range?{q}", timeout=30) as resp:
        res = json.loads(resp.read())["data"]["result"]
    if not res:
        return []
    return [(float(t), float(v) if v not in ("NaN", "+Inf", "-Inf") else float("nan"))
            for t, v in res[0]["values"]]


def align(*series):
    """Inner-join [(ts,val)] series on timestamp; returns (ts_list, [vals...])."""
    maps = [dict(s) for s in series]
    ts = sorted(set(maps[0])) if maps else []
    for m in maps[1:]:
        ts = [t for t in ts if t in m]
    return ts, [[m[t] for t in ts] for m in maps]


def desired(sum_q, sum_r):
    """Reconstruct the HPA's desired replica count from the two AverageValue
    triggers: each metric asks for ceil(aggregate / threshold); the HPA takes the
    max, clamped to [NMIN, NMAX]."""
    if any(math.isnan(x) for x in (sum_q, sum_r)):
        return float("nan")
    d = max(math.ceil(sum_q / Q_THRESH), math.ceil(sum_r / R_THRESH))
    return max(NMIN, min(NMAX, d))


def main():
    start_iso = os.environ.get("RUN_START")
    if not start_iso:
        sys.exit("set RUN_START to the ramp's launch time, e.g. RUN_START=2026-01-01T00:00:00Z")
    start = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end_iso = os.environ.get("RUN_END")
    end = (int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
           if end_iso else int(datetime.now(timezone.utc).timestamp()))
    print(f"window: {start_iso} .. {datetime.fromtimestamp(end, timezone.utc).isoformat()} "
          f"({(end - start) / 60:.1f} min)  prom: {PROM_URL}")

    q_sum = promql_range(f"sum(llm_d_epp_flow_control_queue_size{{{EPP_SEL}}})", start, end)
    r_sum = promql_range(f"sum(llm_d_epp_request_running{{{EPP_SEL}}})", start, end)
    sat = promql_range(
        f'max(llm_d_epp_flow_control_pool_saturation{{namespace="{NS_DEPLOY}",inference_pool="{INFERENCE_POOL}"}})',
        start, end)
    n_s = promql_range(f'max(kube_deployment_status_replicas{{deployment="{DEPLOY}",namespace="{NS_DEPLOY}"}})', start, end)
    r_rdy = promql_range(f'max(kube_deployment_status_replicas_ready{{deployment="{DEPLOY}",namespace="{NS_DEPLOY}"}})', start, end)
    # TTFT is the quality metric of record: the replica saving only counts if it holds.
    ttft_p50 = promql_range(
        f'histogram_quantile(0.5, sum(rate(vllm:time_to_first_token_seconds_bucket{{{VLLM_SEL}}}[1m])) by (le))',
        start, end)
    ttft_p90 = promql_range(
        f'histogram_quantile(0.9, sum(rate(vllm:time_to_first_token_seconds_bucket{{{VLLM_SEL}}}[1m])) by (le))',
        start, end)

    if not n_s:
        sys.exit("no replica series returned - check PROM_URL, DEPLOY/NS_DEPLOY, and the window")

    # per-replica AverageValue the HPA evaluates (aggregate / provisioned replicas)
    ts_q, (qa, nqa) = align(q_sum, n_s)
    queue_avg = [(q / n if n else float("nan")) for q, n in zip(qa, nqa)]
    ts_r, (ra, nra) = align(r_sum, n_s)
    run_avg = [(r / n if n else float("nan")) for r, n in zip(ra, nra)]
    # reconstructed desired from the aggregate signals
    ts_d, (qd, rd) = align(q_sum, r_sum)
    des = [desired(q, r) for q, r in zip(qd, rd)]

    t0 = start
    mins = lambda ts: [(t - t0) / 60 for t in ts]
    xs = lambda s: [(t - t0) / 60 for t, _ in s]
    ys = lambda s: [v for _, v in s]

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": SURF,
                         "axes.facecolor": SURF, "axes.grid": True, "grid.color": GRIDC,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(5, 1, figsize=(10, 13.5), sharex=True)

    ax[0].plot(mins(ts_q), queue_avg, color=BLUE, lw=2, label="queue size / replica")
    ax[0].axhline(Q_THRESH, color=AMBER, ls="--", lw=1.5, label=f"threshold {Q_THRESH:g}")
    ax[0].set_ylabel("queue (AvgValue)")
    ax[0].legend(loc="upper left", frameon=False)

    ax[1].plot(mins(ts_r), run_avg, color=BLUE, lw=2, label="running / replica")
    ax[1].axhline(R_THRESH, color=AMBER, ls="--", lw=1.5, label=f"threshold {R_THRESH:g}")
    ax[1].set_ylabel("running (AvgValue)")
    ax[1].legend(loc="upper left", frameon=False)

    ax[2].plot(xs(sat), ys(sat), color=BLUE, lw=2, label="pool saturation")
    ax[2].axhline(1.0, color=AMBER, ls="--", lw=1.5, label="saturated (1.0)")
    ax[2].set_ylabel("saturation")
    ax[2].legend(loc="upper left", frameon=False)

    ax[3].plot(xs(n_s), ys(n_s), color=BLUE, lw=2, drawstyle="steps-post", label="provisioned")
    ax[3].plot(xs(r_rdy), ys(r_rdy), color=AQUA, lw=2, ls=":", drawstyle="steps-post", label="ready")
    ax[3].plot(mins(ts_d), des, color=MUTED, lw=1.5, ls="--", drawstyle="steps-post", label="desired (reconstructed)")
    ax[3].set_ylabel("replicas")
    ax[3].set_ylim(NMIN - 0.5, NMAX + 0.5)
    ax[3].legend(loc="upper left", frameon=False, ncol=3)

    # TTFT next to replicas: the saving holds only if this stays flat as replicas drop.
    ax[4].plot(xs(ttft_p90), ys(ttft_p90), color=BLUE, lw=2, label="TTFT p90")
    ax[4].plot(xs(ttft_p50), ys(ttft_p50), color=AQUA, lw=1.5, ls=":", label="TTFT p50")
    if TTFT_REF is not None:
        ax[4].axhline(TTFT_REF, color=AMBER, ls="--", lw=1.5, label=f"ref {TTFT_REF:g}s")
    ax[4].set_ylabel("TTFT (s)")
    ax[4].set_xlabel("minutes into run")
    ax[4].legend(loc="upper left", frameon=False)

    fig.tight_layout()
    os.makedirs(DIR, exist_ok=True)
    out = os.path.join(DIR, "queue-run-overview.png")
    fig.savefig(out, dpi=200, bbox_inches="tight")

    # cost: time-averaged provisioned replicas vs a static peak-sized pool
    vals = [v for _, v in n_s if not math.isnan(v)]
    avg_reps = sum(vals) / len(vals) if vals else float("nan")
    peak = max(vals) if vals else float("nan")
    print("\n===== COST =====")
    print(f"avg replicas:   {avg_reps:.2f}")
    print(f"peak replicas:  {peak:.0f}")
    print(f"vs static-peak: {peak:.0f} (saving ~{(1 - avg_reps / peak) * 100:.0f}% replica-time)" if peak else "")
    print(f"plot: {out}")


if __name__ == "__main__":
    main()
