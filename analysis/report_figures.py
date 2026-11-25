#!/usr/bin/env python3
"""Figures used in the final report (final_draft/report_source/figures/), drawn from
the per-run tables written by analyze.py.

    python3 analysis/analyze.py            # writes analysis/out/A_runs.csv, B_runs.csv
    python3 analysis/report_figures.py [--out final_draft/report_source/figures]

loss-goodput.pdf   Part A goodput by injected loss, medians + runs + Mathis reference
competition.pdf    Part B BBR share and P95 excess RTT by queue size
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from analyze import MATHIS_C, MSS_BITS, RTT_S  # noqa: E402

INK, TICK, REF, GRID = "#172F40", "#49606E", "#667D89", "#DCE5EA"
STYLE = {
    "bbr": dict(color="#235A8D", marker="o", ls="-", label="BBRv1"),
    "cubic": dict(color="#A84723", marker="s", ls="--", label="CUBIC"),
    "reno": dict(color="#227561", marker="^", ls="-", label="Reno"),
}
W_IN = 6.25  # 450 pt, the text width used in the report

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.labelcolor": INK, "text.color": INK,
    "axes.edgecolor": GRID, "axes.linewidth": 0.8, "xtick.color": TICK, "ytick.color": TICK,
    "xtick.major.size": 0, "ytick.major.size": 0, "ytick.minor.size": 0,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "legend.frameon": False, "pdf.fonttype": 42, "savefig.bbox": "standard",
})


def runs_and_median(ax, x, values, st, run_alpha, ms_run=4.5):
    """Range of the runs (min to max) as a thin bar behind the median marker.

    The five runs are often nearly identical, so separate run markers hid behind the median
    marker and only showed as a faint halo; a range bar shows the same spread without that.
    """
    v = np.sort(np.asarray(values, float))
    ax.vlines(x, v[0], v[-1], color=st["color"], alpha=run_alpha, lw=1.3, zorder=3)
    return np.median(v)


def loss_goodput(A, out):
    losses = sorted(A.loss_pct.unique())
    offs = {"bbr": -0.13, "cubic": 0.0, "reno": 0.13}
    fig, ax = plt.subplots(figsize=(W_IN, 2.38), layout="constrained")
    for cc, off in offs.items():
        st = STYLE[cc]
        med = [runs_and_median(ax, i + off, A[(A.cc == cc) & (A.loss_pct == p)].goodput_mbps,
                               st, 0.6) for i, p in enumerate(losses)]
        ax.plot(np.arange(len(losses)) + off, med, color=st["color"], ls=st["ls"], lw=1.7,
                marker=st["marker"], ms=7, zorder=4, label=st["label"])
    nz = [i for i, p in enumerate(losses) if p > 0]
    mathis = [MATHIS_C * MSS_BITS / (RTT_S * np.sqrt(losses[i] / 100)) / 1e6 for i in nz]
    ax.plot(nz, mathis, ls=":", color=REF, lw=1.6, zorder=2, label="Mathis reference")
    ax.set_yscale("log")
    ax.set_yticks([2, 5, 10, 20, 50, 100])
    ax.set_yticklabels(["2", "5", "10", "20", "50", "100"])
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_ylim(1.3, 125)
    ax.set_xticks(range(len(losses)))
    ax.set_xticklabels([f"{p:g}%" for p in losses])
    ax.set_xlim(-0.5, len(losses) - 0.5)
    ax.set_xlabel("Injected random loss")
    ax.set_ylabel("Goodput (Mb/s, log scale)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, handlelength=2.4,
              columnspacing=1.6, borderaxespad=0.2)
    fig.savefig(out / "loss-goodput.pdf")
    plt.close(fig)


def competition(B, out):
    qs = sorted(B.queue_bdp.unique())
    x = np.arange(len(qs))
    fig, axes = plt.subplots(1, 2, figsize=(W_IN, 2.35), layout="constrained")
    panels = [
        (axes[0], B.bbr_share * 100, STYLE["bbr"]["color"], "BBR goodput share (%)",
         lambda v: f"{v:.1f}%"),
        (axes[1], B.excess_rtt_p95, STYLE["cubic"]["color"], "P95 excess RTT (ms)",
         lambda v: f"{v:.1f}"),
    ]
    for ax, col, color, ylab, fmt in panels:
        st = dict(marker="o", color=color)
        med = [runs_and_median(ax, i, col[B.queue_bdp == q], st, 0.56) for i, q in enumerate(qs)]
        ax.plot(x, med, color=color, lw=1.9, marker="o", ms=7.5, zorder=4)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{q:g}" for q in qs])
        ax.set_xlim(-0.4, len(qs) - 0.6)
        ax.set_xlabel("Queue size (BDP)")
        ax.set_ylabel(ylab)
        ax._med, ax._fmt, ax._color = med, fmt, color

    a = axes[0]
    a.axhline(50, color=REF, ls="--", lw=1.2, zorder=1)
    a.set_ylim(0, 112)
    a.set_yticks([0, 25, 50, 75, 100])
    a.yaxis.get_gridlines()[2].set_visible(False)  # the dashed 50% line replaces it
    # labels above the points, except where the point sits just under the 50% line
    for i, v in enumerate(a._med):
        below = 40 < v < 50
        a.annotate(a._fmt(v), (i, v), xytext=(0, -9 if below else 7), textcoords="offset points",
                   ha="center", va="top" if below else "bottom", color=a._color,
                   fontsize=9, fontweight="bold")

    a = axes[1]
    a.set_ylim(0, 222)
    a.set_yticks([0, 50, 100, 150, 200])
    # the line rises steeply after the middle point, so its label goes below-right
    for i, v in enumerate(a._med):
        mid = 0 < i < len(a._med) - 1
        a.annotate(a._fmt(v), (i, v), xytext=(7, -5) if mid else (0, 7), textcoords="offset points",
                   ha="left" if mid else "center", va="top" if mid else "bottom",
                   color=a._color, fontsize=9, fontweight="bold")

    fig.savefig(out / "competition.pdf")
    plt.close(fig)


def main():
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", default=repo / "analysis" / "out", type=Path)
    ap.add_argument("--out", default=repo / "final_draft" / "report_source" / "figures", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    loss_goodput(pd.read_csv(args.tables / "A_runs.csv"), args.out)
    competition(pd.read_csv(args.tables / "B_runs.csv"), args.out)
    print(f"wrote {args.out / 'loss-goodput.pdf'} and {args.out / 'competition.pdf'}")


if __name__ == "__main__":
    main()
