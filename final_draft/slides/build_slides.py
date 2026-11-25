#!/usr/bin/env python3
"""Build the final-seminar slides as one self-contained HTML file.

    python3 final_draft/slides/build_slides.py

Charts are inline SVG computed from analysis/out/A_runs.csv and B_runs.csv, so the
slides always show the same numbers as the report. Style: "Science Presentation"
aesthetic from the slides skill (Arctic Frost palette, Plus Jakarta Sans).
Press N during the talk to show the speaker notes.
"""
import html
import math
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "ii2202-group5-seminar-slides.html"
A = pd.read_csv(REPO / "analysis" / "out" / "A_runs.csv")
B = pd.read_csv(REPO / "analysis" / "out" / "B_runs.csv")

MATHIS_C, MSS_BITS, RTT_S = 0.93, 1448 * 8, 0.050  # same constants as analysis/analyze.py
SERIES = {  # colour + marker per algorithm, fixed order
    "bbr": ("BBRv1", "var(--c-bbr)", "circle"),
    "cubic": ("CUBIC", "var(--c-cubic)", "square"),
    "reno": ("Reno", "var(--c-reno)", "triangle"),
}
esc = html.escape


# ------------------------------------------------------------------ SVG helpers
def marker(kind, x, y, r, color, cls="", extra=""):
    if kind == "circle":
        return f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" {extra}/>'
    if kind == "square":
        return (f'<rect class="{cls}" x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" '
                f'fill="{color}" {extra}/>')
    h = r * 1.2
    pts = f"{x:.1f},{y - h:.1f} {x - h:.1f},{y + h * 0.8:.1f} {x + h:.1f},{y + h * 0.8:.1f}"
    return f'<polygon class="{cls}" points="{pts}" fill="{color}" {extra}/>'


def loss_chart():
    W, H, l, r, t, b = 660, 330, 62, 14, 12, 50
    pw, ph = W - l - r, H - t - b
    losses = sorted(A.loss_pct.unique())
    lo, hi = math.log(1.3), math.log(125)
    X = lambda i, off=0.0: l + (i + 0.5 + off) * pw / len(losses)  # noqa: E731
    Y = lambda v: t + ph * (1 - (math.log(v) - lo) / (hi - lo))  # noqa: E731
    s = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="lossTitle lossDesc">',
         '<title id="lossTitle">Goodput by injected loss</title>',
         '<desc id="lossDesc">Median goodput of five runs per condition on a log scale. BBRv1 stays near '
         '90 Mb/s; CUBIC and Reno fall to under 2 Mb/s at 2% loss, slightly above the Mathis reference.</desc>']
    for v in (2, 5, 10, 20, 50, 100):
        y = Y(v)
        s.append(f'<line class="gl" x1="{l}" x2="{W - r}" y1="{y:.1f}" y2="{y:.1f}"/>')
        s.append(f'<text class="tick" x="{l - 10}" y="{y + 4:.1f}" text-anchor="end">{v}</text>')
    for i, p in enumerate(losses):
        s.append(f'<text class="tick" x="{X(i):.1f}" y="{t + ph + 22}" text-anchor="middle">{p:g}%</text>')
    s.append(f'<text class="axis" x="{l + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">Injected random loss</text>')
    s.append(f'<text class="axis" transform="translate(16 {t + ph / 2:.1f}) rotate(-90)" '
             'text-anchor="middle">Goodput (Mb/s, log scale)</text>')
    # Mathis reference at the category centres
    nz = [i for i, p in enumerate(losses) if p > 0]
    pts = " ".join(f"{X(i):.1f},{Y(MATHIS_C * MSS_BITS / (RTT_S * math.sqrt(losses[i] / 100)) / 1e6):.1f}"
                   for i in nz)
    s.append(f'<polyline class="ref enter-trace" style="--delay:0.9s" pathLength="1" points="{pts}"/>')
    offs = {"bbr": -0.13, "cubic": 0.0, "reno": 0.13}
    for k, (cc, off) in enumerate(offs.items()):
        name, color, kind = SERIES[cc]
        meds = []
        for i, p in enumerate(losses):
            v = A[(A.cc == cc) & (A.loss_pct == p)].goodput_mbps.sort_values().to_list()
            for j, x in enumerate(v):
                s.append(marker(kind, X(i, off) + (j - 2) * 2.2, Y(x), 3, color, "run"))
            meds.append(sorted(v)[len(v) // 2])
        path = " ".join(f"{X(i, off):.1f},{Y(m):.1f}" for i, m in enumerate(meds))
        s.append('<g class="series">')
        s.append(f'<polyline class="med enter-trace" style="--delay:{0.2 + 0.2 * k:.1f}s" pathLength="1" '
                 f'points="{path}" stroke="{color}"/>')
        for i, m in enumerate(meds):
            s.append(marker(kind, X(i, off), Y(m), 6.5, color, "med-pt enter-pop",
                            f'style="--delay:{0.35 + 0.2 * k + 0.08 * i:.2f}s"'))
        s.append("</g>")
    s.append("</svg>")
    return "\n".join(s)


def queue_chart(col, scale, ymax, ticks, color, ylab, fmt, ref=None, title="", desc=""):
    W, H, l, r, t, b = 320, 300, 58, 12, 26, 50
    pw, ph = W - l - r, H - t - b
    qs = sorted(B.queue_bdp.unique())
    X = lambda i: l + (i + 0.5) * pw / len(qs)  # noqa: E731
    Y = lambda v: t + ph * (1 - v / ymax)  # noqa: E731
    cid = col.replace("_", "")
    s = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{cid}T {cid}D">',
         f'<title id="{cid}T">{esc(title)}</title><desc id="{cid}D">{esc(desc)}</desc>']
    for v in ticks:
        if ref is not None and v == ref:
            continue
        s.append(f'<line class="gl" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
    for v in ticks:
        s.append(f'<text class="tick" x="{l - 9}" y="{Y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    if ref is not None:
        s.append(f'<line class="ref-line" x1="{l}" x2="{W - r}" y1="{Y(ref):.1f}" y2="{Y(ref):.1f}"/>')
        s.append(f'<text class="ref-label" x="{l + 6}" y="{Y(ref) - 6:.1f}" text-anchor="start">even split</text>')
    for i, q in enumerate(qs):
        s.append(f'<text class="tick" x="{X(i):.1f}" y="{t + ph + 22}" text-anchor="middle">{q:g}</text>')
    s.append(f'<text class="axis" x="{l + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">Queue size (BDP)</text>')
    s.append(f'<text class="axis" transform="translate(15 {t + ph / 2:.1f}) rotate(-90)" '
             f'text-anchor="middle">{esc(ylab)}</text>')
    meds = []
    for i, q in enumerate(qs):
        v = (B[B.queue_bdp == q][col] * scale).sort_values().to_list()
        for j, x in enumerate(v):
            s.append(marker("circle", X(i) + (j - 2) * 2.5, Y(x), 3.2, color, "run"))
        meds.append(sorted(v)[len(v) // 2])
    path = " ".join(f"{X(i):.1f},{Y(m):.1f}" for i, m in enumerate(meds))
    s.append(f'<polyline class="med enter-trace" style="--delay:0.2s" pathLength="1" points="{path}" '
             f'stroke="{color}"/>')
    for i, m in enumerate(meds):
        s.append(marker("circle", X(i), Y(m), 7, color, "med-pt enter-pop", f'style="--delay:{0.3 + 0.15 * i:.2f}s"'))
        below = ref is not None and ref - 10 < m < ref  # keep the label off the reference line
        mid = 0 < i < len(meds) - 1 and ref is None     # steep rise after the middle point
        if below:
            x, y, anchor = X(i), Y(m) + 24, "middle"
        elif mid:
            x, y, anchor = X(i) + 11, Y(m) + 18, "start"
        else:
            x, y, anchor = X(i), Y(m) - 13, "middle"
        s.append(f'<text class="val enter-fade" style="--delay:{0.5 + 0.15 * i:.2f}s; fill:{color}" '
                 f'x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{fmt(m)}</text>')
    s.append("</svg>")
    return "\n".join(s)


# ------------------------------------------------------------------ numbers used in text
med = A.groupby(["cc", "loss_pct"]).goodput_mbps.median()
gb = B.groupby("queue_bdp")
agg = gb.agg_goodput_mbps.median()
jain = gb.jain.median()
p95 = gb.excess_rtt_p95.median()
retain = {cc: med[(cc, 2.0)] / med[(cc, 0.0)] * 100 for cc in SERIES}

NOTES = [  # written to be spoken: short sentences, mixed with longer ones
    "Hi everyone, we're Group 5. Today we compare three TCP congestion control algorithms: BBRv1, CUBIC, "
    "and Reno. Everything ran on the real Linux TCP stack, over one emulated network path. We collected the "
    "data on 23 November.",

    "So why look at this? A link can be fully used and still treat flows very differently. We asked two "
    "kinds of questions. First, one flow on its own: what happens when random loss goes up? Second, two "
    "flows sharing a bottleneck: does the queue size change who gets the bandwidth, and what does it cost "
    "in delay? The path stays the same throughout, 100 Mb/s with a 50 ms round trip. "
    "Our expectations going in were simple. At 2% loss, BBRv1 should keep at least 90% of its goodput, and "
    "CUBIC and Reno less than half. With two flows, BBRv1's share should drop as the queue gets deeper. "
    "The deepest queue should add the most delay. The shallowest should cause the most retransmissions.",

    "A bit of background. Reno and CUBIC both treat loss as the signal to slow down. Reno roughly halves "
    "its window. CUBIC backs off less and grows back faster. The Mathis model gives a rough prediction for "
    "Reno: throughput falls with the square root of the loss rate. And when loss is frequent, CUBIC ends up "
    "behaving a lot like Reno. BBRv1 is different. It builds a model of bandwidth and round-trip time "
    "instead. It still has to resend lost packets, though. Earlier experiments found that buffer size "
    "changes how BBR and CUBIC share a link. That's why we vary the queue.",

    "Here's the testbed. Three network namespaces on one machine. The router is the bottleneck: a "
    "100 Mb/s token bucket with a plain drop-tail queue. The 50 ms delay sits on the ACK path. In Part A, "
    "a separate netem on the sender drops packets at random. "
    "Part B has two flows, and the second one starts five seconds after the first. For each queue size, "
    "BBR went first in three runs and CUBIC in two. Every condition got five runs, in shuffled order. "
    "One caveat: we ran this on WSL2, not on bare metal as we first planned.",

    "A word on data quality, because our first check failed. At 0.5% loss we only measured 0.078%. "
    "Once we capped GSO to one segment, it read 0.494%. After that fix, every validation check passed. "
    "One run hit 100% CPU, so we ran it again. "
    "For the analysis, we skip the start-up and use a fixed window. In Part B, time counts from the first "
    "flow's start, and the window ends at 300 seconds. To check that sharing had settled, we compared the "
    "first and last 30-second blocks. We also redid the key numbers over just the last 120 seconds. Each "
    "run counts once. The medians and ranges you'll see are over those five runs.",

    "First result, one flow at a time. Note the log scale on the y-axis. BBRv1 barely moves. At 2% loss "
    "it still keeps 96% of its goodput. CUBIC and Reno fall fast. At 2% they keep under 2% of their "
    "baseline, 1.7 and 1.9 percent. The dotted line is the Mathis prediction, using the constant for "
    "delayed ACKs. Both sit a little above it. "
    "One thing we got wrong: we expected the gap between CUBIC and Reno to shrink at high loss. It grew "
    "instead, from 0.10 to 0.17 Mb/s. Small, but the wrong direction. "
    "And without injected loss, BBRv1 had the lowest delay: 12.3 ms of P95 excess RTT, against about 48 "
    "for CUBIC and 47 for Reno. At 2% loss, all three resent about 19 or 20 segments per thousand.",

    "Now two flows, one BBRv1 and one CUBIC. On the left is BBR's share of the goodput. The dashed line "
    "is an even split. With a shallow queue, a quarter of a BDP, BBR takes almost everything, about 97%. "
    "At 1 BDP it still has 85%. At 4 BDP it flips. BBR gets 43.5%, so CUBIC now has the bigger part. "
    "The right chart shows the price. Going from 0.25 to 4 BDP adds about 182 ms to the P95 delay. "
    "Retransmissions peak in the shallow queue: about 6 per thousand for BBR, 14 for CUBIC. "
    "All 15 runs passed our stability check, and the pattern holds over the last 120 seconds as well.",

    "To wrap up. Within the range we tested, the picture is quite clear. BBRv1 held up under random loss. "
    "CUBIC and Reno did not. In a shared bottleneck, queue size decided who got the bandwidth. And total "
    "throughput stayed high the whole time, even when the split was very unequal. So throughput alone "
    "would have hidden all of this. The deepest queue gave the fairest split, but also the longest delay. "
    "For our hypotheses: the retention part of H1 held, H2 held at both ends of the range, and H3's "
    "delay and retransmission patterns held. What we didn't test is loss and queue size together, or "
    "exactly where the two shares cross.",

    "That's all from us. The appendix of the report points to the raw data and the analysis scripts, if "
    "you'd like to check our numbers. We're happy to take questions. For example, about the losses in "
    "the shallow queue, how much the analysis window matters, or how newer BBR versions differ.",
]


def slide(i, label, body, cls="", center=False):
    style = ' style="align-items:center;text-align:center;"' if center else ""
    return f'''
<section class="slide {cls}" id="slide-{i}" role="region" aria-label="Slide {i}: {esc(label)}" data-slide-index="{i - 1}">
  <div class="slide-bg" aria-hidden="true"></div>
  <div class="slide-content"{style}>
{body}
  </div>
  <footer class="slide-meta" aria-hidden="true"><span>II2202 · Group 5</span><span>{i:02d} / {len(NOTES):02d}</span></footer>
  <aside class="notes" aria-label="Speaker notes">{esc(NOTES[i - 1])}</aside>
</section>'''


def legend(keys, ref=False):
    items = []
    for k in keys:
        name, color, kind = SERIES[k]
        svg = marker(kind, 9, 7, 5, color)
        line = f'<line x1="0" x2="18" y1="7" y2="7" stroke="{color}" stroke-width="2.5"/>'
        items.append(f'<li><svg viewBox="0 0 18 14" aria-hidden="true">{line}{svg}</svg>{name}</li>')
    if ref:
        items.append('<li><svg viewBox="0 0 18 14" aria-hidden="true"><line x1="0" x2="18" y1="7" y2="7" '
                     'class="ref" /></svg>Mathis reference</li>')
    return '<ul class="legend" role="list">' + "".join(items) + "</ul>"


slides = []
slides.append(slide(1, "Title", f'''
    <p class="label enter-fade-up">II2202 · Group 5 · Final seminar</p>
    <h1 class="title enter-fade-up" style="--delay:0.1s">Random Loss, Queue Size,<br>and TCP Congestion Control</h1>
    <p class="subtitle enter-fade-up" style="--delay:0.2s">Comparing BBRv1, CUBIC, and Reno on an emulated bottleneck</p>
    <div class="title-stats enter-fade-up" style="--delay:0.35s">
      <div><span class="stat-num">100 Mb/s</span><span class="stat-label">Bottleneck rate</span></div>
      <div><span class="stat-num">50 ms</span><span class="stat-label">Base round-trip time</span></div>
      <div><span class="stat-num">75</span><span class="stat-label">Measured runs</span></div>
    </div>
    <p class="presenters enter-fade-up" style="--delay:0.5s">Hongen Wang · Yuanyu Zhang<span class="sep">KTH · Autumn 2026</span></p>''',
    cls="slide-title"))

slides.append(slide(2, "Research problem", '''
    <p class="label enter-fade-up">Research problem</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">Why loss and queue depth matter</h2>
    <p class="lead enter-fade-up" style="--delay:0.1s">A busy link can still give one flow very little capacity or impose long delays.</p>
    <div class="grid grid-2">
      <article class="card enter-fade-up" style="--delay:0.2s">
        <p class="card-kicker">RQ1</p><h3>Single-flow loss response</h3>
        <p>How do goodput, retransmissions, and excess RTT change for BBRv1, CUBIC, and Reno as random loss rises?</p>
      </article>
      <article class="card enter-fade-up" style="--delay:0.3s">
        <p class="card-kicker">RQ2 and RQ3</p><h3>Sharing a bottleneck</h3>
        <p>How does queue size affect BBRv1–CUBIC sharing, aggregate goodput, retransmissions, and delay?</p>
      </article>
    </div>
    <p class="scope enter-fade-up" style="--delay:0.4s">Scope · One emulated path · Bulk TCP · Drop-tail queue</p>'''))

slides.append(slide(3, "Background", '''
    <p class="label enter-fade-up">Background</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">How the senders respond to loss</h2>
    <div class="grid grid-3">
      <article class="card algo enter-fade-up" style="--delay:0.15s; --algo:var(--c-reno)">
        <h3>Reno</h3><p>Increases its window by about one segment per RTT. Roughly halves it on loss.</p><p class="ref-tag">RFC 5681</p></article>
      <article class="card algo enter-fade-up" style="--delay:0.25s; --algo:var(--c-cubic)">
        <h3>CUBIC</h3><p>Grows its window with a cubic function of time. Keeps about 70% on loss.</p><p class="ref-tag">RFC 9438</p></article>
      <article class="card algo enter-fade-up" style="--delay:0.35s; --algo:var(--c-bbr)">
        <h3>BBRv1</h3><p>Estimates delivery bandwidth and minimum RTT. Uses them to pace and limit inflight data.</p><p class="ref-tag">Cardwell et al. (2017)</p></article>
    </div>
    <p class="callout enter-fade-up" style="--delay:0.45s">Prior experiments found that buffer depth changes the BBRv1–CUBIC split <span class="ref-tag">Jaeger et al. (2019)</span></p>'''))

slides.append(slide(4, "Method: testbed", '''
    <p class="label enter-fade-up">Method</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">A controlled Linux bottleneck</h2>
    <p class="lead small-lead enter-fade-up" style="--delay:0.1s">Three network namespaces on one WSL2 host · Ubuntu 24.04 · iperf3 3.16</p>
    <div class="topo enter-fade-up" style="--delay:0.2s">
      <div class="node"><strong>Sender</strong><span>iperf3 client(s)</span><em class="tag tag-loss">random loss (Part A)</em></div>
      <div class="link"><span class="data">Data →</span><span class="ack">← ACKs</span></div>
      <div class="node node-key"><strong>Router</strong><span>100 Mb/s token bucket</span><em class="tag">50 ms delay on ACK path</em></div>
      <div class="link"><span class="data">Data →</span><span class="ack">← ACKs</span></div>
      <div class="node"><strong>Receiver</strong><span>one server per flow</span></div>
    </div>
    <div class="grid grid-2">
      <article class="card enter-fade-up" style="--delay:0.3s">
        <p class="card-kicker">Part A · 60 single-flow runs</p>
        <p>BBRv1, CUBIC, or Reno · 120 s<br>0%, 0.1%, 0.5%, or 2% loss · 1 BDP queue</p></article>
      <article class="card enter-fade-up" style="--delay:0.4s">
        <p class="card-kicker">Part B · 15 competition runs</p>
        <p>BBRv1 + CUBIC · 300 s per flow<br>0.25, 1, or 4 BDP queue · no injected loss</p></article>
    </div>
    <p class="scope enter-fade-up" style="--delay:0.5s">One bandwidth-delay product (BDP) = 625,000 bytes</p>'''))

slides.append(slide(5, "Method: analysis", '''
    <p class="label enter-fade-up">Method</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">From raw logs to run-level metrics</h2>
    <p class="lead small-lead enter-fade-up" style="--delay:0.1s">A fixed analysis window after start-up, then five runs per condition.</p>
    <div class="timeline enter-fade-up" style="--delay:0.2s">
      <div class="tl-row"><span class="tl-name">A</span><div class="tl-bar" style="--warm:16.67%"><span class="warm">0–20 s</span><span class="win">20–120 s analysis</span></div></div>
      <div class="tl-row"><span class="tl-name">B</span><div class="tl-bar" style="--warm:20%"><span class="warm">0–60 s</span><span class="win">60–300 s analysis</span></div></div>
    </div>
    <div class="grid grid-3">
      <article class="card enter-fade-up" style="--delay:0.3s"><p class="card-kicker">Receiver JSON</p><p>Payload goodput, share, and Jain’s index</p></article>
      <article class="card enter-fade-up" style="--delay:0.38s"><p class="card-kicker">TCP socket counters</p><p>Retransmissions per 1,000 outgoing data segments</p></article>
      <article class="card enter-fade-up" style="--delay:0.46s"><p class="card-kicker">Ping and TBF</p><p>P50, P95, and P99 above idle RTT, plus queue backlog</p></article>
    </div>
    <p class="scope enter-fade-up" style="--delay:0.55s">Validation · 50.30 ms idle RTT · 0.494% measured at 0.5% loss · 75 valid runs</p>'''))

slides.append(slide(6, "Results RQ1", f'''
    <p class="label enter-fade-up">Results · RQ1</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">BBRv1 kept {retain["bbr"]:.0f}% of its goodput at 2% loss</h2>
    <div class="chart-row">
      <figure class="chart-fig enter-fade-up" style="--delay:0.1s">
        {legend(["bbr", "cubic", "reno"], ref=True)}
        {loss_chart()}
      </figure>
      <div class="side-stats">
        <p class="side-head enter-fade-up" style="--delay:0.2s">At 2% injected loss</p>
        <div class="stat enter-fade-up" style="--delay:0.3s; --algo:var(--c-bbr)"><span class="stat-num">{med[("bbr", 2.0)]:.2f}</span><span class="stat-unit">Mb/s</span><span class="stat-label">BBRv1</span></div>
        <div class="stat enter-fade-up" style="--delay:0.4s; --algo:var(--c-cubic)"><span class="stat-num">{med[("cubic", 2.0)]:.2f}</span><span class="stat-unit">Mb/s</span><span class="stat-label">CUBIC</span></div>
        <div class="stat enter-fade-up" style="--delay:0.5s; --algo:var(--c-reno)"><span class="stat-num">{med[("reno", 2.0)]:.2f}</span><span class="stat-unit">Mb/s</span><span class="stat-label">Reno</span></div>
      </div>
    </div>
    <p class="insight enter-fade-up" style="--delay:0.6s">At 0% injected loss, all three exceeded 93 Mb/s. BBRv1 had the lowest P95 excess RTT.</p>'''))

share_fmt = lambda v: f"{v:.1f}%"  # noqa: E731
slides.append(slide(7, "Results RQ2 and RQ3", f'''
    <p class="label enter-fade-up">Results · RQ2 and RQ3</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">A deeper queue evened the split but added {p95[4.0] - p95[0.25]:.0f}&nbsp;ms of P95 delay</h2>
    <div class="chart-row two">
      <figure class="chart-fig enter-fade-up" style="--delay:0.1s">
        <figcaption>BBRv1 share of goodput</figcaption>
        {queue_chart("bbr_share", 100, 110, [0, 25, 50, 75, 100], "var(--c-bbr)", "BBR goodput share (%)",
                     share_fmt, ref=50, title="BBR goodput share by queue size",
                     desc="Median BBR share falls from 96.8% at 0.25 BDP to 85.0% at 1 BDP and 43.5% at 4 BDP.")}
      </figure>
      <figure class="chart-fig enter-fade-up" style="--delay:0.2s">
        <figcaption>P95 excess RTT</figcaption>
        {queue_chart("excess_rtt_p95", 1, 220, [0, 50, 100, 150, 200], "var(--c-delay)", "P95 excess RTT (ms)",
                     lambda v: f"{v:.1f}", title="P95 excess RTT by queue size",
                     desc="Median P95 excess RTT rises from 11.0 ms at 0.25 BDP to 42.8 ms at 1 BDP and 192.7 ms at 4 BDP.")}
      </figure>
      <div class="side-stats">
        <div class="stat enter-fade-up" style="--delay:0.3s"><span class="stat-num sm">{agg[0.25]:.1f} → {agg[4.0]:.1f}</span><span class="stat-unit">Mb/s</span><span class="stat-label">Aggregate goodput</span></div>
        <div class="stat enter-fade-up" style="--delay:0.4s"><span class="stat-num sm">{jain[0.25]:.3f} → {jain[4.0]:.3f}</span><span class="stat-label">Jain’s index</span></div>
        <div class="stat enter-fade-up" style="--delay:0.5s"><span class="stat-num sm">0.25 BDP</span><span class="stat-label">Most retransmissions, for both flows</span></div>
      </div>
    </div>
    <p class="insight enter-fade-up" style="--delay:0.6s">One BBRv1 flow and one CUBIC flow · five runs per queue · no injected loss</p>'''))

slides.append(slide(8, "Conclusion and future work", f'''
    <p class="label enter-fade-up">Conclusion and future work</p>
    <h2 class="heading enter-fade-up" style="--delay:0.05s">Aggregate goodput barely moved; sharing and delay did</h2>
    <div class="grid grid-2 concl">
      <article class="card enter-fade-up" style="--delay:0.15s">
        <p class="card-kicker">What the experiment showed</p>
        <ul class="bullet-list">
          <li>BBRv1 kept most of its goodput at 2% random loss. CUBIC and Reno each retained below 2%.</li>
          <li>At 0.25 BDP, BBRv1 dominated the split and both flows retransmitted most often.</li>
          <li>At 4 BDP, sharing was more even and P95 excess RTT was {p95[4.0] - p95[0.25]:.1f} ms higher than at 0.25 BDP.</li>
        </ul></article>
      <article class="card enter-fade-up" style="--delay:0.3s">
        <p class="card-kicker">Next experiments</p>
        <ul class="bullet-list">
          <li>Test intermediate queue sizes with longer overlaps and balanced starts.</li>
          <li>Compare a newer BBR version and active queue management on bare-metal Linux.</li>
        </ul></article>
    </div>
    <p class="scope enter-fade-up" style="--delay:0.45s">Scope · BBRv1 · Equal 50 ms base RTTs · One 100 Mb/s drop-tail bottleneck</p>'''))

slides.append(slide(9, "Questions", '''
    <h2 class="closing enter-fade-up">Questions?</h2>
    <p class="presenters enter-fade-up" style="--delay:0.15s">Hongen Wang · Yuanyu Zhang</p>''', cls="slide-closing", center=True))

HERE = Path(__file__).resolve().parent
base_css = (HERE / "viewport-base.css").read_text()  # copied from the slides skill

CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
:root {
  --bg: #f0f4f8; --surface: #ffffff; --surface-2: #e8edf2; --border: #d1d9e2;
  --text: #1a2332; --text-muted: #4a5568; --accent: #2563eb; --accent-2: #0ea5e9;
  --c-bbr: #2563eb; --c-cubic: #1e3a8a; --c-reno: #14a3c7; --c-ref: #64748b; --c-delay: #334155; --grid: #dde4ec;
  --font-display: 'Plus Jakarta Sans', 'Segoe UI', sans-serif; --font-body: 'Plus Jakarta Sans', 'Segoe UI', sans-serif;
  --shadow-sm: 0 1px 2px rgba(26,35,50,.06);
  --shadow-md: 0 4px 14px rgba(26,35,50,.08), 0 1px 3px rgba(26,35,50,.06);
  --shadow-lg: 0 16px 40px rgba(26,35,50,.12);
  --stat-size: clamp(1.4rem, 3.2vw, 2.6rem); --stat-sm-size: clamp(1rem, 2vw, 1.5rem);
  --lead-size: clamp(0.95rem, 1.9vw, 1.4rem);
}
html { font-size: clamp(16px, 1.04vw, 22px); }  /* scale everything up on 1080p+ projectors */
body { background: var(--bg); color: var(--text); font-family: var(--font-body); overflow: hidden; }
.slide { background: var(--bg); }
.slide-bg { position: absolute; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    radial-gradient(ellipse 60% 50% at 88% 8%, rgba(14,165,233,.10), transparent 70%),
    radial-gradient(ellipse 50% 45% at 5% 100%, rgba(37,99,235,.08), transparent 70%),
    linear-gradient(rgba(37,99,235,.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(37,99,235,.045) 1px, transparent 1px);
  background-size: auto, auto, 32px 32px, 32px 32px; }
.slide-content { position: relative; z-index: 1; max-width: min(1560px, 100%); width: 100%; margin: 0 auto;
  padding: clamp(2.5rem, 7vh, 5rem) clamp(1.5rem, 6vw, 5rem); }
.label { color: var(--accent); font-weight: 700; }
.heading { font-family: var(--font-display); font-weight: 800; max-width: 40ch; text-wrap: balance; }
h1.title { font-family: var(--font-display); font-weight: 800; font-size: clamp(2rem, 5.2vw, 4.4rem); text-wrap: balance; }
h3 { font-family: var(--font-display); font-weight: 700; font-size: var(--h3-size); }
.subtitle, .lead { font-size: var(--lead-size); color: var(--text-muted); max-width: 62ch; }
.small-lead { font-size: var(--body-size); }
.card { background: var(--surface); border: var(--border-width) solid var(--border); border-radius: var(--radius-md);
  padding: var(--card-padding); box-shadow: var(--shadow-md); max-width: none; display: flex; flex-direction: column;
  gap: var(--element-gap); }
.card p { color: var(--text-muted); font-size: clamp(0.85rem, 1.6vw, 1.2rem); }
.card-kicker { color: var(--accent) !important; font-weight: 700; font-size: var(--label-size) !important;
  letter-spacing: .1em; text-transform: uppercase; }
.card.algo { border-top: 4px solid var(--algo); }
.card.algo h3 { color: var(--text); }
.ref-tag { font-size: var(--small-size) !important; color: var(--text-muted); opacity: .8; }
.callout { font-size: var(--lead-size); border-left: 4px solid var(--accent); padding-left: 1rem; max-width: 72ch; }
.scope { font-size: var(--small-size); color: var(--text-muted); letter-spacing: .04em; }
.slide-meta { position: absolute; z-index: 1; left: clamp(1.5rem, 6vw, 5rem); right: clamp(1.5rem, 6vw, 5rem);
  top: clamp(0.8rem, 2.5vh, 1.6rem); display: flex; justify-content: space-between; font-size: var(--label-size);
  letter-spacing: .12em; text-transform: uppercase; color: var(--text-muted); }
/* title */
.slide-title .slide-content { gap: clamp(0.8rem, 2.5vh, 1.6rem); }
.title-stats { display: flex; gap: clamp(1rem, 4vw, 3.5rem); margin-top: clamp(0.5rem, 2vh, 1.5rem);
  padding-top: clamp(0.8rem, 2vh, 1.4rem); border-top: var(--border-width) solid var(--border); width: fit-content; }
.title-stats div { display: flex; flex-direction: column; }
.stat-num { font-family: var(--font-display); font-weight: 800; font-size: var(--stat-size); line-height: 1.05;
  font-variant-numeric: tabular-nums; }
.stat-num.sm { font-size: var(--stat-sm-size); }
.stat-label { font-size: var(--small-size); color: var(--text-muted); }
.stat-unit { font-size: var(--small-size); color: var(--text-muted); margin-left: .3em; }
.presenters { font-size: var(--body-size); font-weight: 600; }
.presenters .sep { font-weight: 400; color: var(--text-muted); margin-left: 1.5em; }
/* topology */
.topo { display: grid; grid-template-columns: 1fr auto 1.15fr auto 1fr; align-items: center; gap: clamp(.3rem, 1vw, .8rem); }
.node { background: var(--surface); border: var(--border-width) solid var(--border); border-radius: var(--radius-md);
  padding: clamp(.6rem, 1.4vw, 1.1rem); box-shadow: var(--shadow-sm); display: flex; flex-direction: column; gap: .2rem;
  text-align: center; font-size: var(--body-size); }
.node-key { border-color: var(--accent); box-shadow: var(--shadow-md); }
.node span { color: var(--text-muted); }
.tag { font-style: normal; font-size: var(--label-size); font-weight: 600; color: var(--accent);
  background: rgba(37,99,235,.08); border-radius: 999px; padding: .15em .7em; margin-top: .3rem; align-self: center; }
.tag-loss { color: var(--c-delay); background: rgba(51,65,85,.08); }
.link { display: flex; flex-direction: column; font-size: var(--small-size); font-weight: 600; gap: .3rem; text-align: center; }
.link .data { color: var(--accent); } .link .ack { color: var(--text-muted); }
/* timeline */
.timeline { display: flex; flex-direction: column; gap: clamp(.4rem, 1.2vh, .8rem); }
.tl-row { display: grid; grid-template-columns: 2rem 1fr; align-items: center; gap: .6rem; }
.tl-name { font-weight: 800; color: var(--accent); font-size: var(--h3-size); }
.tl-bar { display: grid; grid-template-columns: var(--warm) 1fr; border-radius: var(--radius-sm); overflow: hidden;
  box-shadow: var(--shadow-sm); font-size: var(--small-size); font-weight: 600; }
.tl-bar span { padding: .55em .8em; white-space: nowrap; }
.warm { background: repeating-linear-gradient(135deg, var(--surface-2) 0 6px, #dfe6ee 6px 12px); color: var(--text-muted); }
.win { background: var(--accent); color: #fff; }
/* charts */
.chart-row { display: grid; grid-template-columns: minmax(0, 2.3fr) minmax(0, 1fr); gap: clamp(1rem, 3vw, 2.5rem); align-items: center; }
.chart-row.two { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, .8fr); }
.chart-fig { background: var(--surface); border: var(--border-width) solid var(--border); border-radius: var(--radius-md);
  padding: clamp(.6rem, 1.4vw, 1.1rem); box-shadow: var(--shadow-md); min-width: 0; }
.chart-fig figcaption { font-size: var(--small-size); font-weight: 700; color: var(--text-muted); }
.chart { width: 100%; height: auto; max-height: 52vh; display: block; }
.chart text { font-family: var(--font-body); }
.chart .tick { fill: var(--text-muted); font-size: 13px; }
.chart .axis { fill: var(--text); font-size: 13px; font-weight: 600; }
.chart .val { font-size: 15px; font-weight: 800; }
.chart .gl { stroke: var(--grid); stroke-width: 1; }
.chart .run { opacity: .38; }
.chart .med { fill: none; stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
.chart .med-pt { stroke: var(--surface); stroke-width: 2; }
.chart .ref, .legend .ref { fill: none; stroke: var(--c-ref); stroke-width: 2.4; stroke-dasharray: .012 .018; stroke-linecap: round; }
.legend .ref { stroke-dasharray: 1 4; }
.chart .ref-line { stroke: var(--c-ref); stroke-width: 1.6; stroke-dasharray: 6 5; }
.chart .ref-label { fill: var(--c-ref); font-size: 12px; font-weight: 600; }
.legend { display: flex; flex-wrap: wrap; gap: .4rem 1.4rem; list-style: none; font-size: var(--small-size);
  font-weight: 600; margin-bottom: .3rem; }
.legend li { display: flex; align-items: center; gap: .45rem; }
.legend svg { width: 1.6em; height: 1.2em; overflow: visible; }
.side-stats { display: flex; flex-direction: column; gap: clamp(.5rem, 1.6vh, 1rem); }
.side-head { font-size: var(--label-size); letter-spacing: .1em; text-transform: uppercase; font-weight: 700; color: var(--text-muted); }
.stat { background: var(--surface); border: var(--border-width) solid var(--border); border-left: 4px solid var(--algo, var(--accent));
  border-radius: var(--radius-sm); padding: clamp(.5rem, 1.2vw, .9rem) clamp(.7rem, 1.4vw, 1.1rem); box-shadow: var(--shadow-sm); }
.stat .stat-label { display: block; font-weight: 600; color: var(--text); }
.insight { font-size: var(--body-size); color: var(--text-muted); border-left: 4px solid var(--accent); padding-left: .9rem; }
.concl .bullet-list li { color: var(--text); font-size: clamp(0.85rem, 1.6vw, 1.2rem); }
.concl .bullet-list li::before { content: "—"; color: var(--accent); font-weight: 800; }
/* closing */
.slide-closing .slide-content { justify-content: center; }
.closing { font-family: var(--font-display); font-weight: 800; font-size: clamp(2.4rem, 7vw, 5.5rem); }
/* speaker notes (press N) */
.notes { display: none; position: absolute; z-index: 5; left: 0; right: 0; bottom: 0; max-height: 34vh; overflow: auto;
  background: rgba(26,35,50,.94); color: #f0f4f8; font-size: var(--small-size); line-height: 1.5;
  padding: 1rem clamp(1.5rem, 6vw, 5rem); box-shadow: var(--shadow-lg); }
body.show-notes .notes { display: block; }
/* entrance animations (animation-patterns.md) */
[class*="enter-"] { animation-fill-mode: both; animation-duration: .7s; animation-delay: var(--delay, 0s);
  animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes fadeUp { from { opacity: 0; transform: translateY(clamp(16px, 3vh, 32px)); } to { opacity: 1; transform: none; } }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes pop { from { opacity: 0; transform: scale(.4); } to { opacity: 1; transform: none; } }
@keyframes trace { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
.enter-fade-up { animation-name: fadeUp; }
.enter-fade { animation-name: fadeIn; }
.enter-pop { animation-name: pop; transform-box: fill-box; transform-origin: center; }
.enter-trace { animation-name: trace; animation-duration: 1.1s; stroke-dasharray: 1 1; }
.chart .ref.enter-trace { stroke-dasharray: .012 .018; animation-name: fadeIn; }
@media (prefers-reduced-motion: reduce) { .enter-trace { stroke-dasharray: none; } }
@media (max-width: 900px) { .chart-row, .chart-row.two { grid-template-columns: 1fr; } .topo { grid-template-columns: 1fr; } }
@media print { .notes { display: none !important; } }
"""

JS_EXTRA = r"""
document.addEventListener('keydown', (e) => {
  if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey) document.body.classList.toggle('show-notes');
});
"""

TEMPLATE_JS = (HERE / "presentation.js").read_text()  # copied from the slides skill

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="II2202 Group 5 final seminar: BBRv1, CUBIC and Reno under random loss and different queue sizes.">
<title>Random Loss, Queue Size, and TCP Congestion Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<style>
{base_css}
{CSS}
</style>
</head>
<body>
<div class="progress-bar" id="progressBar" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" aria-label="Presentation progress" style="color:var(--accent)"></div>
<nav class="nav-dots" id="navDots" aria-label="Slide navigation" style="color:var(--accent)"></nav>
<p class="keyboard-hint" aria-hidden="true">← → or Space to navigate · N for notes · F for full screen</p>
{''.join(slides)}
<script>
{TEMPLATE_JS}
{JS_EXTRA}
</script>
</body>
</html>
"""
OUT.write_text(page, encoding="utf-8")
print(f"wrote {OUT} ({len(page) / 1024:.0f} KB, {len(slides)} slides)")
