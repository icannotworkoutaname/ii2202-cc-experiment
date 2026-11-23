#!/usr/bin/env python3
"""Plot pilot runs: per-flow receiver rate, TBF queueing delay, ping excess RTT,
and print BBR's share in 30-s blocks to judge when the runs settle.

    python3 analysis/pilot_plot.py [pilot]
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse  # noqa: E402

base = Path(sys.argv[1] if len(sys.argv) > 1 else "pilot")
runs = sorted(d for d in base.iterdir() if (d / "meta.json").exists())
fig, axes = plt.subplots(3, len(runs), figsize=(5 * len(runs), 8), sharex=True, squeeze=False)

for j, d in enumerate(runs):
    m = parse.meta(d)
    T0 = parse.t0(m)
    idle = parse.idle_rtt_ms(d)
    rates = {}
    for f in m["flows"]:
        r = parse.receiver_intervals(d, m, f["cc"])
        r["t"] = r["epoch_end"] - T0
        rates[f["cc"]] = r
        axes[0, j].plot(r["t"], r["mbps"], label=f["cc"], lw=0.8)
    q = parse.tbf(d)
    axes[1, j].plot(q["epoch"] - T0, q["qdelay_ms"], lw=0.5)
    p = parse.ping(d)
    axes[2, j].plot(p["epoch"] - T0, p["rtt_ms"] - idle, ",", alpha=0.4)

    axes[0, j].set_title(f"{d.name}  (queue {m['queue_bdp']} BDP)")
    axes[0, j].set_ylabel("receiver Mb/s")
    axes[1, j].set_ylabel("TBF queue delay (ms)")
    axes[2, j].set_ylabel("ping excess RTT (ms)")
    axes[2, j].set_xlabel("time since first flow (s)")
    axes[0, j].legend()
    for a in axes[:, j]:
        a.axvline(60, color="grey", ls="--", lw=0.6)

    # BBR share in 30-s blocks
    b, c = rates["bbr"], rates["cubic"]
    print(f"\n{d.name}: queue {m['queue_bdp']} BDP, idle RTT {idle:.2f} ms, "
          f"max CPU {m['max_core_busy_pct']}%, status {m['status']} {m['errors']}")
    line = []
    for s in range(0, 300, 30):
        xb = b[(b.t > s) & (b.t <= s + 30)].mbps.mean()
        xc = c[(c.t > s) & (c.t <= s + 30)].mbps.mean()
        line.append(f"{s:>3}-{s + 30:<3}s {xb / (xb + xc):.2f}")
    print("  BBR share per 30 s:  " + " | ".join(line))
    w = (b.t > 60) & (b.t <= 300)
    wc = (c.t > 60) & (c.t <= 300)
    xb, xc = b[w].mbps.mean(), c[wc].mbps.mean()
    print(f"  window 60-300 s: BBR {xb:.1f}  CUBIC {xc:.1f}  sum {xb + xc:.1f} Mb/s  "
          f"share {xb / (xb + xc):.2f}  Jain {(xb + xc) ** 2 / (2 * (xb**2 + xc**2)):.3f}")
    print(f"  qdisc drops: {parse.qdisc_counters(d)}")

fig.tight_layout()
out = base / "pilot_traces.png"
fig.savefig(out, dpi=120)
print(f"\nfigure: {out}")
