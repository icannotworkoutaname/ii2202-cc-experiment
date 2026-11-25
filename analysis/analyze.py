#!/usr/bin/env python3
"""All tables and figures for RQ1-RQ3 from the run directories.

    python3 analysis/analyze.py [--runs runs] [--out analysis/out]

Only runs whose meta.json has status "ok" are used. Outputs:
  A_runs.csv, B_runs.csv            one row per run
  A_summary.csv/.tex, B_summary.csv/.tex   median [Q1, Q3] per condition
  tests.csv                         exact two-sided Mann-Whitney tests for H1-H3
  steady_state.csv                  Part B 30-s blocks + last-120-s recompute
  fig_A.png, fig_B.png, fig_B_traces.png
"""
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse  # noqa: E402

WIN = {"A": (20, 120), "B": (60, 300)}
LAST120 = (180, 300)
# Mathis et al. (1997) constant for random loss with delayed ACKs: the receiver
# acknowledged 2.4-2.8 data segments per ACK in the lossy CUBIC/Reno runs.
MSS_BITS, RTT_S, MATHIS_C = 1448 * 8, 0.050, 0.93
CC_ORDER = ["bbr", "cubic", "reno"]
STYLE = {  # fixed categorical order + shape as a second channel for print
    "bbr": dict(color="#2a78d6", marker="o", label="BBR"),
    "cubic": dict(color="#eb6834", marker="s", label="CUBIC"),
    "reno": dict(color="#1baf7a", marker="^", label="Reno"),
}
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3dd"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "savefig.dpi": 300, "savefig.bbox": "tight",
})


# ---------------------------------------------------------------- per-run metrics
def in_win(t, lo, hi):
    return (t > lo) & (t <= hi)


def flow_metrics(d, m, T0, ss_df, cc, lo, hi):
    r = parse.receiver_intervals(d, m, cc)
    t = r["epoch_end"] - T0
    w = r[in_win(t, lo, hi)]
    span = (w["epoch_end"] - w["epoch_start"]).sum()
    goodput = w["bytes"].sum() * 8 / span / 1e6 if span else np.nan
    s = ss_df[(ss_df.cc == cc)].copy()
    s["t"] = s["epoch"] - T0
    s["retrans_total"] = s["retrans_total"].fillna(0)
    sw = s[in_win(s["t"], lo, hi)]
    if len(sw) >= 2:
        segs = sw["data_segs_out"].iloc[-1] - sw["data_segs_out"].iloc[0]
        rtx = sw["retrans_total"].iloc[-1] - sw["retrans_total"].iloc[0]
    else:
        segs = rtx = np.nan
    return {"goodput_mbps": goodput, "retrans_segs": rtx, "data_segs": segs,
            "retrans_per_1000": 1000 * rtx / segs if segs else np.nan}


def path_metrics(d, T0, idle, lo, hi):
    p = parse.ping(d)
    pw = p[in_win(p["epoch"] - T0, lo, hi)]
    ex = pw["rtt_ms"] - idle
    q = parse.tbf(d)
    qw = q[in_win(q["epoch"] - T0, lo, hi)]
    return {"excess_rtt_p50": ex.quantile(.5), "excess_rtt_p95": ex.quantile(.95),
            "excess_rtt_p99": ex.quantile(.99), "ping_samples": len(pw),
            "tbf_qdelay_mean_ms": qw["qdelay_ms"].mean(),
            "tbf_drops_win": qw["dropped"].iloc[-1] - qw["dropped"].iloc[0] if len(qw) else np.nan}


def run_metrics(d):
    m = parse.meta(d)
    part = "B" if m["part"] in ("B", "pilot") else "A"
    lo, hi = WIN[part]
    T0, idle = parse.t0(m), parse.idle_rtt_ms(d)
    ss_df = parse.ss(d, m)
    qc = parse.qdisc_counters(d)
    row = {"run_id": m["run_id"], "part": part, "queue_bdp": float(m["queue_bdp"]),
           "rep": int(m["rep"]), "idle_rtt_ms": idle, "max_core_busy_pct": m["max_core_busy_pct"],
           "netem_drops_run": qc.get("s0", {}).get("dropped", 0),
           "tbf_drops_run": qc["r1"]["dropped"], "delay_netem_drops": qc["r0"]["dropped"],
           **{f"nstat_{k}": v for k, v in parse.nstat_delta(d).items()},
           **path_metrics(d, T0, idle, lo, hi)}
    if part == "A":
        cc = m["ccs"]
        row.update(cc=cc, loss_pct=float(m["loss_pct"]),
                   **flow_metrics(d, m, T0, ss_df, cc, lo, hi),
                   iperf_retransmits_run=parse.sender_summary(d, cc)["retransmits"])
        row["utilization"] = row["goodput_mbps"] / 100
    else:
        row["first"] = m["flows"][0]["cc"]
        for cc in ("bbr", "cubic"):
            for k, v in flow_metrics(d, m, T0, ss_df, cc, lo, hi).items():
                row[f"{cc}_{k}"] = v
        xb, xc = row["bbr_goodput_mbps"], row["cubic_goodput_mbps"]
        row.update(agg_goodput_mbps=xb + xc, utilization=(xb + xc) / 100,
                   bbr_share=xb / (xb + xc), jain=(xb + xc) ** 2 / (2 * (xb**2 + xc**2)))
        row.update(steady_state(d, m, T0, idle, ss_df))
    return row


def steady_state(d, m, T0, idle, ss_df):
    lo, hi = WIN["B"]
    rates = {}
    for cc in ("bbr", "cubic"):
        r = parse.receiver_intervals(d, m, cc)
        r["t"] = r["epoch_end"] - T0
        rates[cc] = r
    blocks = []
    for s in range(lo, hi, 30):
        xb = rates["bbr"][in_win(rates["bbr"].t, s, s + 30)]["bytes"].sum()
        xc = rates["cubic"][in_win(rates["cubic"].t, s, s + 30)]["bytes"].sum()
        blocks.append(xb / (xb + xc))
    out = {"block_share_first": blocks[0], "block_share_last": blocks[-1],
           "settled": abs(blocks[-1] - blocks[0]) <= 0.10,
           "block_shares": " ".join(f"{b:.3f}" for b in blocks)}
    l_lo, l_hi = LAST120
    fb = flow_metrics(d, m, T0, ss_df, "bbr", l_lo, l_hi)["goodput_mbps"]
    fc = flow_metrics(d, m, T0, ss_df, "cubic", l_lo, l_hi)["goodput_mbps"]
    pm = path_metrics(d, T0, idle, l_lo, l_hi)
    out.update(last120_bbr_share=fb / (fb + fc), last120_jain=(fb + fc) ** 2 / (2 * (fb**2 + fc**2)),
               last120_agg_goodput_mbps=fb + fc, last120_excess_rtt_p50=pm["excess_rtt_p50"],
               last120_excess_rtt_p95=pm["excess_rtt_p95"])
    return out


# ---------------------------------------------------------------- summaries
def summarize(df, by, cols):
    g = df.groupby(by)[cols]
    med, q1, q3, n = g.median(), g.quantile(.25), g.quantile(.75), g.size()
    out = med.add_suffix("_median").join(q1.add_suffix("_q1")).join(q3.add_suffix("_q3"))
    out["n"] = n
    return out.reset_index()


def latex_table(summary, by, cols, fmt, path):
    lines = []
    for _, r in summary.iterrows():
        keys = [str(r[b]) for b in by]
        vals = [f"{r[c + '_median']:{fmt[c]}} [{r[c + '_q1']:{fmt[c]}}, {r[c + '_q3']:{fmt[c]}}]"
                for c in cols]
        lines.append(" & ".join(keys + vals) + r" \\")
    head = " & ".join(by + [c.replace("_", r"\_") for c in cols]) + r" \\ \hline"
    Path(path).write_text("\\begin{tabular}{" + "l" * len(by) + "r" * len(cols) + "}\n"
                          + head + "\n" + "\n".join(lines) + "\n\\end{tabular}\n")


def mw(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2:
        return np.nan, np.nan
    res = mannwhitneyu(a, b, alternative="two-sided", method="exact")
    return res.statistic, res.pvalue


def hypothesis_tests(A, B):
    rows = []

    def add(h, desc, a, b):
        u, p = mw(a, b)
        rows.append({"hypothesis": h, "comparison": desc, "median_1": np.median(a) if len(a) else np.nan,
                     "median_2": np.median(b) if len(b) else np.nan, "n1": len(a), "n2": len(b),
                     "U": u, "p_exact_two_sided": p,
                     "ranges_overlap": bool(len(a) and len(b) and max(min(a), min(b)) <= min(max(a), max(b)))})

    if len(A):
        for cc in CC_ORDER:
            g = A[A.cc == cc]
            g0, g2 = g[g.loss_pct == 0].goodput_mbps, g[g.loss_pct == 2].goodput_mbps
            add("H1", f"{cc} goodput: 0% vs 2% loss", g0, g2)
            if len(g0) and len(g2):
                rows[-1]["ratio_median_2_over_0"] = np.median(g2) / np.median(g0)
        for loss in (0.1, 2):
            g = A[A.loss_pct == loss]
            add("H1", f"goodput at {loss}%: cubic vs reno",
                g[g.cc == "cubic"].goodput_mbps, g[g.cc == "reno"].goodput_mbps)
    if len(B):
        q = lambda x, col: B[B.queue_bdp == x][col]  # noqa: E731
        add("H2", "BBR share: 0.25 vs 4 BDP", q(0.25, "bbr_share"), q(4, "bbr_share"))
        add("H2", "BBR share: 0.25 vs 1 BDP", q(0.25, "bbr_share"), q(1, "bbr_share"))
        add("H2", "BBR share: 1 vs 4 BDP", q(1, "bbr_share"), q(4, "bbr_share"))
        for col in ("excess_rtt_p50", "excess_rtt_p95"):
            add("H3", f"{col}: 0.25 vs 4 BDP", q(0.25, col), q(4, col))
            add("H3", f"{col}: 1 vs 4 BDP", q(1, col), q(4, col))
        for cc in ("bbr", "cubic"):
            col = f"{cc}_retrans_per_1000"
            add("H3", f"{col}: 0.25 vs 1 BDP", q(0.25, col), q(1, col))
            add("H3", f"{col}: 0.25 vs 4 BDP", q(0.25, col), q(4, col))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- figures
def strip(ax, df, xcol, ycol, xs, offsets, styles):
    """All runs as points plus a median tick, one group per (x, series)."""
    for key, off in offsets.items():
        st = styles[key]
        for i, x in enumerate(xs):
            sub = df(key, x)[ycol].dropna()
            if sub.empty:
                continue
            xx = np.full(len(sub), i + off)
            ax.scatter(xx, sub, s=22, color=st["color"], marker=st["marker"],
                       edgecolors="white", linewidths=0.6, zorder=3,
                       label=st["label"] if i == 0 else None)
            ax.hlines(sub.median(), i + off - 0.11, i + off + 0.11, color=INK, lw=1.2, zorder=4)
    ax.set_xticks(range(len(xs)))


def fig_A(A, out):
    losses = sorted(A.loss_pct.unique())
    offs = {"bbr": -0.22, "cubic": 0.0, "reno": 0.22}
    sel = lambda cc, x: A[(A.cc == cc) & (A.loss_pct == x)]  # noqa: E731
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.6))
    panels = [("goodput_mbps", "Goodput (Mb/s, log scale)"),
              ("retrans_per_1000", "Retransmitted segments per 1000"),
              ("excess_rtt_p50", "Excess RTT P50 (ms)"), ("excess_rtt_p95", "Excess RTT P95 (ms)")]
    for ax, (col, lab) in zip(axes.flat, panels):
        strip(ax, sel, "loss_pct", col, losses, offs, STYLE)
        ax.set_xticklabels([f"{x:g}%" for x in losses])
        ax.set_xlabel("Injected random loss")
        ax.set_ylabel(lab)
    ax = axes[0, 0]
    ax.set_yscale("log")
    mx = [i for i, x in enumerate(losses) if x > 0]
    mathis = [MATHIS_C * MSS_BITS / (RTT_S * np.sqrt(losses[i] / 100)) / 1e6 for i in mx]
    ax.plot(mx, mathis, ls="--", color=MUTED, lw=1, zorder=2, label=f"Mathis (C = {MATHIS_C})")
    ax.axhline(95.6, color=MUTED, lw=0.8, ls=":", zorder=2)
    ax.text(len(losses) - 0.5, 95.6, "header limit", color=MUTED, fontsize=7, ha="right", va="bottom")
    axes[0, 0].legend(loc="lower left", fontsize=8)
    fig.suptitle("Part A: one flow, 1 BDP queue, window 20-120 s (points = runs, bar = median)",
                 fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(out / "fig_A.png")
    plt.close(fig)


def fig_B(B, out):
    qs = sorted(B.queue_bdp.unique())
    one = {"x": dict(color="#2a78d6", marker="o", label=None)}
    selq = lambda _, x: B[B.queue_bdp == x]  # noqa: E731
    fig, axes = plt.subplots(2, 3, figsize=(9.6, 5.6))
    for ax, (col, lab) in zip(axes.flat[:3], [("bbr_share", "BBR share of goodput"),
                                              ("jain", "Jain's fairness index"),
                                              ("agg_goodput_mbps", "Aggregate goodput (Mb/s)")]):
        strip(ax, selq, "queue_bdp", col, qs, {"x": 0}, one)
        ax.set_ylabel(lab)
    axes[0, 0].axhline(0.5, color=MUTED, ls="--", lw=0.8)
    axes[0, 0].set_ylim(0, 1)
    axes[0, 1].set_ylim(0.5, 1.0)
    axes[0, 2].set_ylim(85, 100)
    axes[0, 2].axhline(95.6, color=MUTED, lw=0.8, ls=":")
    axes[0, 2].text(2.4, 95.6, "header limit", color=MUTED, fontsize=7, ha="right", va="bottom")
    # per-flow retransmissions
    ax = axes[1, 0]
    long = pd.concat([B.assign(cc=cc, v=B[f"{cc}_retrans_per_1000"]) for cc in ("bbr", "cubic")])
    strip(ax, lambda cc, x: long[(long.cc == cc) & (long.queue_bdp == x)].rename(columns={"v": "val"}),
          "queue_bdp", "val", qs, {"bbr": -0.15, "cubic": 0.15}, STYLE)
    ax.set_ylabel("Retransmitted segments per 1000")
    ax.legend(fontsize=8)
    # excess RTT percentiles
    ax = axes[1, 1]
    pst = {"excess_rtt_p50": dict(color="#2a78d6", marker="o", label="P50"),
           "excess_rtt_p95": dict(color="#eb6834", marker="s", label="P95"),
           "excess_rtt_p99": dict(color="#1baf7a", marker="^", label="P99")}
    longr = pd.concat([B.assign(k=k, val=B[k]) for k in pst])
    strip(ax, lambda k, x: longr[(longr.k == k) & (longr.queue_bdp == x)], "queue_bdp", "val", qs,
          {"excess_rtt_p50": -0.2, "excess_rtt_p95": 0, "excess_rtt_p99": 0.2}, pst)
    ax.set_ylabel("Excess RTT (ms)")
    ax.legend(fontsize=8)
    ax = axes[1, 2]
    strip(ax, selq, "queue_bdp", "tbf_qdelay_mean_ms", qs, {"x": 0}, one)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Mean TBF queueing delay (ms)")
    for ax in axes.flat:
        ax.set_xticklabels([f"{q:g}" for q in qs])
        ax.set_xlabel("Bottleneck queue (BDP)")
    fig.suptitle("Part B: 1 BBR + 1 CUBIC, no injected loss, window 60-300 s "
                 "(points = runs, bar = median)", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(out / "fig_B.png")
    plt.close(fig)


def fig_B_traces(runs_dir, B, out, rep=1):
    qs = sorted(B.queue_bdp.unique())
    fig, axes = plt.subplots(2, len(qs), figsize=(3.4 * len(qs), 4.6), sharex=True, squeeze=False)
    for j, q in enumerate(qs):
        rid = B[(B.queue_bdp == q) & (B.rep == rep)].run_id
        if rid.empty:
            continue
        d = Path(runs_dir) / rid.iloc[0]
        m = parse.meta(d)
        T0 = parse.t0(m)
        for cc in ("bbr", "cubic"):
            r = parse.receiver_intervals(d, m, cc)
            r = r[(r["epoch_end"] - r["epoch_start"]) >= 0.5]  # drop iperf3's short last interval
            axes[0, j].plot(r["epoch_end"] - T0, r["mbps"], color=STYLE[cc]["color"], lw=1,
                            label=STYLE[cc]["label"])
        tq = parse.tbf(d)
        tq["sec"] = np.floor(tq["epoch"] - T0)
        q1s = tq.groupby("sec")["qdelay_ms"].mean()  # 1-s mean of the 100-ms samples
        axes[1, j].plot(q1s.index + 1, q1s.values, color=MUTED, lw=1)
        axes[1, j].set_ylim(bottom=0)
        axes[0, j].set_title(f"{q:g} BDP (rep {rep})", fontsize=9, color=INK)
        axes[1, j].set_xlabel("Time since first flow (s)")
        for a in axes[:, j]:
            a.axvspan(0, WIN["B"][0], color=GRID, alpha=0.5, lw=0)
    axes[0, 0].set_ylabel("Receiver goodput (Mb/s)")
    axes[1, 0].set_ylabel("TBF queueing delay, 1-s mean (ms)")
    axes[0, 0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "fig_B_traces.png")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="analysis/out")
    args = ap.parse_args()
    runs_dir, out = Path(args.runs), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows, skipped = [], []
    for d in sorted(p for p in runs_dir.iterdir() if (p / "meta.json").exists()):
        if parse.meta(d).get("status") != "ok":
            skipped.append(d.name)
            continue
        rows.append(run_metrics(d))
    df = pd.DataFrame(rows)
    A = df[df.part == "A"].copy() if len(df) else pd.DataFrame()
    B = df[df.part == "B"].copy() if len(df) else pd.DataFrame()
    print(f"runs used: A={len(A)} B={len(B)}  skipped (not ok): {skipped}")

    if len(A):
        A.to_csv(out / "A_runs.csv", index=False)
        cols = ["goodput_mbps", "retrans_per_1000", "excess_rtt_p50", "excess_rtt_p95",
                "excess_rtt_p99", "tbf_drops_win", "netem_drops_run"]
        sA = summarize(A, ["cc", "loss_pct"], cols)
        sA.to_csv(out / "A_summary.csv", index=False)
        latex_table(sA, ["cc", "loss_pct"], cols[:5], {c: ".1f" for c in cols}, out / "A_summary.tex")
        fig_A(A, out)
    if len(B):
        B.to_csv(out / "B_runs.csv", index=False)
        cols = ["bbr_share", "jain", "agg_goodput_mbps", "bbr_retrans_per_1000",
                "cubic_retrans_per_1000", "excess_rtt_p50", "excess_rtt_p95", "excess_rtt_p99",
                "tbf_qdelay_mean_ms", "tbf_drops_win"]
        sB = summarize(B, ["queue_bdp"], cols)
        sB.to_csv(out / "B_summary.csv", index=False)
        fmt = {c: ".1f" for c in cols} | {"bbr_share": ".2f", "jain": ".3f"}
        latex_table(sB, ["queue_bdp"], cols[:8], fmt, out / "B_summary.tex")
        B[["run_id", "queue_bdp", "rep", "first", "block_shares", "block_share_first",
           "block_share_last", "settled", "bbr_share", "last120_bbr_share", "jain", "last120_jain",
           "agg_goodput_mbps", "last120_agg_goodput_mbps", "excess_rtt_p50",
           "last120_excess_rtt_p50", "excess_rtt_p95", "last120_excess_rtt_p95"]
          ].to_csv(out / "steady_state.csv", index=False)
        fig_B(B, out)
        fig_B_traces(runs_dir, B, out)
    hypothesis_tests(A, B).to_csv(out / "tests.csv", index=False)
    print(f"outputs in {out}")


if __name__ == "__main__":
    main()
