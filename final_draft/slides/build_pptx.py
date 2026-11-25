#!/usr/bin/env python3
"""Build the final-seminar deck as an editable PowerPoint file with speaker notes.

    python3 final_draft/slides/build_pptx.py      # needs python-pptx (pip install python-pptx)

Same content, numbers and notes as build_slides.py (the HTML version); the charts are
native PowerPoint charts computed from analysis/out/A_runs.csv and B_runs.csv.
"""
import io
import math
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFilter
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

import build_slides as hs  # reuse the data, numbers and speaker notes of the HTML deck

HERE = Path(__file__).resolve().parent
OUT = HERE / "ii2202-group5-seminar-slides.pptx"
A, B, med, agg, jain, p95, retain, NOTES = hs.A, hs.B, hs.med, hs.agg, hs.jain, hs.p95, hs.retain, hs.NOTES


def rgb(h):
    return RGBColor.from_string(h)


BG, SURFACE, BORDER, TEXT, MUTED = "F0F4F8", "FFFFFF", "D1D9E2", "1A2332", "4A5568"
ACCENT, TINT, GRID, REF, DELAY = "2563EB", "E6EEFB", "DDE4EC", "64748B", "334155"
ALGO = {"bbr": ("BBRv1", "2563EB", "circle"), "cubic": ("CUBIC", "1E3A8A", "square"),
        "reno": ("Reno", "14A3C7", "triangle")}
SHAPE = {"circle": MSO_SHAPE.OVAL, "square": MSO_SHAPE.RECTANGLE, "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE}
MARK = {"circle": XL_MARKER_STYLE.CIRCLE, "square": XL_MARKER_STYLE.SQUARE, "triangle": XL_MARKER_STYLE.TRIANGLE}
FONT = "Calibri"
SW, SH, L = 13.333, 7.5, 0.75          # slide size and left margin (inches)
CW = SW - 2 * L                         # content width
TOP = 2.35                              # where content starts under the title


# ------------------------------------------------------------------ background image
def background_png():
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), "#" + BG)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((int(.88 * W) - 620, int(.08 * H) - 330, int(.88 * W) + 620, int(.08 * H) + 330), fill=(14, 165, 233, 30))
    d.ellipse((int(.05 * W) - 520, H - 300, int(.05 * W) + 520, H + 300), fill=(37, 99, 235, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img.paste(glow, (0, 0), glow)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for x in range(0, W, 32):
        g.line([(x, 0), (x, H)], fill=(37, 99, 235, 12))
    for y in range(0, H, 32):
        g.line([(0, y), (W, y)], fill=(37, 99, 235, 12))
    img.paste(grid, (0, 0), grid)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def set_master_background(prs):
    """Put the grid background on the slide master so every slide inherits it."""
    master = prs.slide_master
    _, rid = master.part.get_or_add_image_part(background_png())
    csld = master._element.find(qn("p:cSld"))
    old = csld.find(qn("p:bg"))
    if old is not None:
        csld.remove(old)
    bg = csld.makeelement(qn("p:bg"), {})
    bgpr = bg.makeelement(qn("p:bgPr"), {})
    fill = bgpr.makeelement(qn("a:blipFill"), {"dpi": "0", "rotWithShape": "1"})
    blip = fill.makeelement(qn("a:blip"), {qn("r:embed"): rid})
    stretch = fill.makeelement(qn("a:stretch"), {})
    stretch.append(stretch.makeelement(qn("a:fillRect"), {}))
    fill.extend([blip, stretch])
    bgpr.extend([fill, bgpr.makeelement(qn("a:effectLst"), {})])
    bg.append(bgpr)
    csld.insert(0, bg)


# ------------------------------------------------------------------ text helpers
def style_run(run, size, color=TEXT, bold=False, italic=False, spacing=None):
    f = run.font
    f.name, f.size, f.bold, f.italic = FONT, Pt(size), bold, italic
    f.color.rgb = rgb(color)
    if spacing is not None:
        run._r.get_or_add_rPr().set("spc", str(int(spacing * 100)))


def fill_frame(tf, paras, anchor=MSO_ANCHOR.TOP, margins=(0, 0, 0, 0)):
    """paras: list of dicts with runs=[(text, {style})] or text=..., plus align/space_after/bullet."""
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = (Inches(m) for m in margins)
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = p.get("align", PP_ALIGN.LEFT)
        if "space_after" in p:
            para.space_after = Pt(p["space_after"])
        if "line" in p:
            para.line_spacing = p["line"]
        if p.get("bullet"):
            ppr = para._p.get_or_add_pPr()
            ppr.set("marL", str(Inches(0.3)))
            ppr.set("indent", str(-Inches(0.3)))
            buclr = ppr.makeelement(qn("a:buClr"), {})
            buclr.append(buclr.makeelement(qn("a:srgbClr"), {"val": ACCENT}))
            ppr.append(buclr)
            ppr.append(ppr.makeelement(qn("a:buFont"), {"typeface": FONT}))
            ppr.append(ppr.makeelement(qn("a:buChar"), {"char": "–"}))
        runs = p.get("runs") or [(p["text"], {k: v for k, v in p.items()
                                               if k in ("size", "color", "bold", "italic", "spacing")})]
        for text, st in runs:
            r = para.add_run()
            r.text = text
            style_run(r, **st)


def text(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, name=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    if isinstance(paras, dict):
        paras = [paras]
    fill_frame(tb.text_frame, paras, anchor)
    return tb


def box(slide, x, y, w, h, fill=SURFACE, line=BORDER, line_w=0.75, radius=0.06, name=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if name:
        s.name = name
    return s


def card(slide, x, y, w, h, paras, name=None, anchor=MSO_ANCHOR.TOP, pad=0.28):
    s = box(slide, x, y, w, h, name=name)
    fill_frame(s.text_frame, paras, anchor, margins=(pad, pad - 0.04, pad, pad - 0.04))
    return s


def icon(slide, kind, color, x, y, size=0.3, name=None):
    s = box(slide, x, y, size, size, fill=color, line=None, shape=SHAPE[kind], name=name)
    return s


def kicker(t, color=ACCENT, size=12, space_after=6):
    return {"text": t.upper(), "size": size, "bold": True, "color": color, "spacing": 1.2, "space_after": space_after}


# ------------------------------------------------------------------ slide frame
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
set_master_background(prs)
TITLE_ONLY = prs.slide_layouts[5]
prs.core_properties.title = "Random Loss, Queue Size, and TCP Congestion Control"
prs.core_properties.author = "Hongen Wang, Yuanyu Zhang"
prs.core_properties.subject = "II2202 Group 5 final seminar"


def new_slide(i, label=None, title=None, title_size=30):
    s = prs.slides.add_slide(TITLE_ONLY)
    text(s, L, 0.32, 6, 0.3, {"text": "II2202 · GROUP 5", "size": 11, "color": MUTED, "spacing": 1.5}, name="Meta")
    text(s, SW - L - 2, 0.32, 2, 0.3, {"text": f"{i:02d} / {len(NOTES):02d}", "size": 11, "color": MUTED,
                                       "spacing": 1.5, "align": PP_ALIGN.RIGHT}, name="Page number")
    if label:
        text(s, L, 0.82, CW, 0.35, {"text": label, "size": 15, "bold": True, "color": ACCENT}, name="Section label")
    t = s.shapes.title
    if title:
        t.left, t.top, t.width, t.height = Inches(L), Inches(1.15), Inches(CW), Inches(1.05)
        fill_frame(t.text_frame, [{"text": title, "size": title_size, "bold": True, "color": TEXT, "line": 0.95}])
    s.notes_slide.notes_text_frame.text = NOTES[i - 1]
    return s


def scope(s, t, y=6.45):
    text(s, L, y, CW, 0.35, {"text": t, "size": 13, "color": MUTED, "spacing": 0.4}, name="Scope note")


def insight(s, t, y=6.38):
    b = box(s, L, y, CW, 0.55, fill=TINT, line=None, radius=0.2, name="Insight")
    fill_frame(b.text_frame, [{"text": t, "size": 15, "color": TEXT}], MSO_ANCHOR.MIDDLE, margins=(0.25, 0, 0.25, 0))


# ------------------------------------------------------------------ charts
def style_chart(chart, legend=True):
    chart.font.name, chart.font.size = FONT, Pt(12)
    chart.font.color.rgb = rgb(MUTED)
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(13)
        chart.legend.font.color.rgb = rgb(TEXT)
    va, ca = chart.value_axis, chart.category_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb(GRID)
    va.major_gridlines.format.line.width = Pt(0.75)
    va.format.line.fill.background()
    ca.format.line.color.rgb = rgb(BORDER)
    for ax in (va, ca):
        ax.tick_labels.font.size = Pt(12)
        ax.tick_labels.font.color.rgb = rgb(MUTED)


def axis_title(ax, t):
    ax.has_title = True
    ax.axis_title.text_frame.text = t
    r = ax.axis_title.text_frame.paragraphs[0].runs[0]
    style_run(r, 12, TEXT, bold=True)


def style_series(ser, color, kind=None, dash=None, width=2.5):
    ser.smooth = False
    ser.format.line.color.rgb = rgb(color)
    ser.format.line.width = Pt(width)
    if dash:
        ser.format.line.dash_style = dash
    if kind:
        ser.marker.style, ser.marker.size = MARK[kind], 9
        ser.marker.format.fill.solid()
        ser.marker.format.fill.fore_color.rgb = rgb(color)
        ser.marker.format.line.color.rgb = rgb(SURFACE)
    else:
        ser.marker.style = XL_MARKER_STYLE.NONE


DRAW_ORDER = ("bbr", "reno", "cubic")  # CUBIC (dashed) drawn over Reno: the two lines nearly coincide


def loss_chart(s, x, y, w, h):
    losses = sorted(A.loss_pct.unique())
    cd = CategoryChartData(number_format="0.0")
    cd.categories = [f"{p:g}%" for p in losses]
    for cc in DRAW_ORDER:
        cd.add_series(ALGO[cc][0], [round(float(med[(cc, p)]), 2) for p in losses])
    cd.add_series("Mathis reference", [None if p == 0 else
                                       round(hs.MATHIS_C * hs.MSS_BITS / (hs.RTT_S * math.sqrt(p / 100)) / 1e6, 2)
                                       for p in losses])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    gf.name = "Goodput by loss chart"
    ch = gf.chart
    style_chart(ch)
    for ser, cc in zip(ch.plots[0].series, DRAW_ORDER):
        _, color, kind = ALGO[cc]
        style_series(ser, color, kind, dash=MSO_LINE_DASH_STYLE.DASH if cc == "cubic" else None)
    style_series(ch.plots[0].series[3], REF, dash=MSO_LINE_DASH_STYLE.ROUND_DOT, width=2.25)
    va = ch.value_axis
    va.minimum_scale, va.maximum_scale = 1, 100
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "0", False
    scaling = va._element.find(qn("c:scaling"))
    scaling.insert(0, scaling.makeelement(qn("c:logBase"), {"val": "10"}))
    va.has_minor_gridlines = True
    minor = va._element.find(qn("c:minorGridlines"))  # python-pptx has no API for minor gridline format
    sppr = minor.makeelement(qn("c:spPr"), {})
    ln = sppr.makeelement(qn("a:ln"), {"w": str(Pt(0.5))})
    sf = ln.makeelement(qn("a:solidFill"), {})
    sf.append(sf.makeelement(qn("a:srgbClr"), {"val": "E6EBF1"}))
    ln.append(sf)
    sppr.append(ln)
    minor.append(sppr)
    axis_title(va, "Goodput (Mb/s, log scale)")
    axis_title(ch.category_axis, "Injected random loss")
    return gf


def queue_chart(s, x, y, w, h, col, scale, ymax, major, color, ytitle, fmt, chart_title, ref=None, name=""):
    qs = sorted(B.queue_bdp.unique())
    meds = [float((B[B.queue_bdp == q][col] * scale).median()) for q in qs]
    cd = CategoryChartData(number_format="0.0")
    cd.categories = [f"{q:g}" for q in qs]
    cd.add_series("Median of five runs", meds)
    if ref is not None:
        cd.add_series("Even split", [ref] * len(qs))
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    gf.name = name
    ch = gf.chart
    style_chart(ch, legend=ref is not None)
    if ref is not None:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.has_title = True
    ch.chart_title.text_frame.text = chart_title
    style_run(ch.chart_title.text_frame.paragraphs[0].runs[0], 14, TEXT, bold=True)
    main = ch.plots[0].series[0]
    style_series(main, color, "circle", width=3)
    main.marker.size = 11
    if ref is not None:
        style_series(ch.plots[0].series[1], REF, dash=MSO_LINE_DASH_STYLE.DASH, width=1.75)
    va = ch.value_axis
    va.minimum_scale, va.maximum_scale, va.major_unit = 0, ymax, major
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "0", False
    axis_title(va, ytitle)
    axis_title(ch.category_axis, "Queue size (BDP)")
    for i, m in enumerate(meds):
        dl = main.points[i].data_label
        dl.text_frame.text = fmt(m)
        style_run(dl.text_frame.paragraphs[0].runs[0], 14, TEXT, bold=True)
        near_ref = ref is not None and ref - 10 < m < ref
        dl.position = XL_LABEL_POSITION.BELOW if near_ref else (
            XL_LABEL_POSITION.RIGHT if 0 < i < len(meds) - 1 and ref is None else XL_LABEL_POSITION.ABOVE)
    return gf


def stat_card(s, x, y, w, h, number, unit, label, kind=None, color=ACCENT, num_size=30, name=None):
    box(s, x, y, w, h, name=name)
    tx = x + 0.25
    if kind:
        icon(s, kind, color, x + 0.25, y + h / 2 - 0.13, 0.26, name=f"{label} marker")
        tx = x + 0.7
    runs = [(number, {"size": num_size, "bold": True, "color": TEXT})]
    if unit:
        runs.append(("  " + unit, {"size": 14, "color": MUTED}))
    text(s, tx, y + 0.08, w - (tx - x) - 0.15, h - 0.16,
         [{"runs": runs, "line": 0.95},
          {"text": label, "size": 14, "bold": True, "color": TEXT if kind else MUTED}],
         anchor=MSO_ANCHOR.MIDDLE)


# ------------------------------------------------------------------ slides
# 1 Title
s = new_slide(1)
text(s, L, 1.35, CW, 0.4, {"text": "II2202 · Group 5 · Final seminar", "size": 17, "bold": True, "color": ACCENT})
t = s.shapes.title
t.left, t.top, t.width, t.height = Inches(L), Inches(1.85), Inches(CW), Inches(1.75)
fill_frame(t.text_frame, [{"text": "Random Loss, Queue Size,", "size": 50, "bold": True, "line": 0.92},
                          {"text": "and TCP Congestion Control", "size": 50, "bold": True, "line": 0.92}])
text(s, L, 3.72, CW, 0.5, {"text": "Comparing BBRv1, CUBIC, and Reno on an emulated bottleneck", "size": 22,
                           "color": MUTED})
for k, (num, lab) in enumerate([("100 Mb/s", "Bottleneck rate"), ("50 ms", "Base round-trip time"),
                                ("75", "Measured runs")]):
    text(s, L + k * 3.0, 4.6, 2.8, 1.0, [{"text": num, "size": 38, "bold": True, "line": 0.95},
                                         {"text": lab, "size": 15, "color": MUTED}], name=f"Stat {lab}")
text(s, L, 6.15, CW, 0.45, {"runs": [("Hongen Wang · Yuanyu Zhang", {"size": 19, "bold": True}),
                                     ("      KTH · Autumn 2026", {"size": 19, "color": MUTED})]})

# 2 Research problem
s = new_slide(2, "Research problem", "Why loss and queue depth matter")
text(s, L, TOP, CW, 0.5, {"text": "A busy link can still give one flow very little capacity or impose long delays.",
                          "size": 20, "color": MUTED})
cw2 = (CW - 0.35) / 2
for k, (kick, head, body) in enumerate([
        ("RQ1", "Single-flow loss response",
         "How do goodput, retransmissions, and excess RTT change for BBRv1, CUBIC, and Reno as random loss rises?"),
        ("RQ2 and RQ3", "Sharing a bottleneck",
         "How does queue size affect BBRv1–CUBIC sharing, aggregate goodput, retransmissions, and delay?")]):
    card(s, L + k * (cw2 + 0.35), 3.15, cw2, 2.75,
         [kicker(kick), {"text": head, "size": 24, "bold": True, "space_after": 10},
          {"text": body, "size": 18, "color": MUTED, "line": 1.1}], name=f"{kick} card", pad=0.35)
scope(s, "Scope · One emulated path · Bulk TCP · Drop-tail queue")

# 3 Background
s = new_slide(3, "Background", "How the senders respond to loss")
cw3 = (CW - 2 * 0.35) / 3
for k, (cc, body, cite) in enumerate([
        ("reno", "Increases its window by about one segment per RTT. Roughly halves it on loss.", "RFC 5681"),
        ("cubic", "Grows its window with a cubic function of time. Keeps about 70% on loss.", "RFC 9438"),
        ("bbr", "Estimates delivery bandwidth and minimum RTT. Uses them to pace and limit inflight data.",
         "Cardwell et al. (2017)")]):
    name, color, kind = ALGO[cc]
    x = L + k * (cw3 + 0.35)
    box(s, x, TOP, cw3, 3.15, name=f"{name} card")
    icon(s, kind, color, x + 0.35, TOP + 0.42, 0.3, name=f"{name} marker")
    text(s, x + 0.8, TOP + 0.3, cw3 - 1.1, 0.55, {"text": name, "size": 26, "bold": True, "color": TEXT},
         anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.35, TOP + 1.05, cw3 - 0.7, 1.3, {"text": body, "size": 18, "color": MUTED, "line": 1.1})
    text(s, x + 0.35, TOP + 2.62, cw3 - 0.7, 0.35, {"text": cite, "size": 13, "color": MUTED, "italic": True})
b = box(s, L, 5.8, CW, 0.75, fill=TINT, line=None, radius=0.2, name="Prior work callout")
fill_frame(b.text_frame, [{"runs": [("Prior experiments found that buffer depth changes the BBRv1–CUBIC split",
                                     {"size": 19, "color": TEXT}),
                                    ("   Jaeger et al. (2019)", {"size": 14, "color": MUTED, "italic": True})]}],
           MSO_ANCHOR.MIDDLE, margins=(0.3, 0, 0.3, 0))

# 4 Method: testbed
s = new_slide(4, "Method", "A controlled Linux bottleneck")
text(s, L, TOP - 0.1, CW, 0.4, {"text": "Three network namespaces on one WSL2 host · Ubuntu 24.04 · iperf3 3.16",
                                "size": 17, "color": MUTED})
nodes = [("Sender", "iperf3 client(s)", ("random loss (Part A)", "334155", "E2E8F0")),
         ("Router", "100 Mb/s token bucket", ("50 ms delay on ACK path", ACCENT, TINT)),
         ("Receiver", "one server per flow", None)]
widths, lw = [3.05, 3.6, 3.05], 1.06
x, ty, th = L, 2.95, 1.45
for k, ((head, sub, tag), nw) in enumerate(zip(nodes, widths)):
    key = head == "Router"
    box(s, x, ty, nw, th, line=ACCENT if key else BORDER, line_w=1.75 if key else 0.75, name=f"{head} node")
    text(s, x + 0.1, ty + 0.14, nw - 0.2, 0.75, [{"text": head, "size": 19, "bold": True, "align": PP_ALIGN.CENTER},
                                                 {"text": sub, "size": 15, "color": MUTED, "align": PP_ALIGN.CENTER}])
    if tag:
        tw = 0.09 * len(tag[0]) + 0.3
        pill = box(s, x + (nw - tw) / 2, ty + 0.95, tw, 0.32, fill=tag[2], line=None, radius=0.5, name=f"{head} tag")
        fill_frame(pill.text_frame, [{"text": tag[0], "size": 12, "bold": True, "color": tag[1],
                                      "align": PP_ALIGN.CENTER}], MSO_ANCHOR.MIDDLE)
    x += nw
    if k < 2:
        text(s, x, ty + 0.38, lw, 0.7, [{"text": "Data →", "size": 13, "bold": True, "color": ACCENT,
                                         "align": PP_ALIGN.CENTER, "space_after": 4},
                                        {"text": "← ACKs", "size": 13, "bold": True, "color": "475569",
                                         "align": PP_ALIGN.CENTER}], name="Link")
        x += lw
for k, (kick, lines) in enumerate([("Part A · 60 single-flow runs",
                                    ["BBRv1, CUBIC, or Reno · 120 s", "0%, 0.1%, 0.5%, or 2% loss · 1 BDP queue"]),
                                   ("Part B · 15 competition runs",
                                    ["BBRv1 + CUBIC · 300 s per flow", "0.25, 1, or 4 BDP queue · no injected loss"])]):
    card(s, L + k * (cw2 + 0.35), 4.7, cw2, 1.5,
         [kicker(kick)] + [{"text": ln, "size": 17, "color": MUTED} for ln in lines], name=f"Part {'AB'[k]} card")
scope(s, "One bandwidth-delay product (BDP) = 625,000 bytes")

# 5 Method: analysis
s = new_slide(5, "Method", "From raw logs to run-level metrics")
text(s, L, TOP - 0.1, CW, 0.4, {"text": "A fixed analysis window after start-up, then five runs per condition.",
                                "size": 17, "color": MUTED})
bx, bw = L + 0.5, CW - 0.5
for k, (part, frac, warm, win) in enumerate([("A", 20 / 120, "0–20 s", "20–120 s analysis"),
                                             ("B", 60 / 300, "0–60 s", "60–300 s analysis")]):
    y = 2.9 + k * 0.6
    text(s, L, y, 0.45, 0.45, {"text": part, "size": 22, "bold": True, "color": ACCENT}, anchor=MSO_ANCHOR.MIDDLE)
    w1 = bw * frac
    a = box(s, bx, y, w1, 0.45, fill="E1E7EE", line=None, shape=MSO_SHAPE.RECTANGLE, name=f"Part {part} warm-up")
    fill_frame(a.text_frame, [{"text": warm, "size": 14, "bold": True, "color": MUTED}], MSO_ANCHOR.MIDDLE,
               margins=(0.15, 0, 0.1, 0))
    b = box(s, bx + w1, y, bw - w1, 0.45, fill=ACCENT, line=None, shape=MSO_SHAPE.RECTANGLE,
            name=f"Part {part} analysis window")
    fill_frame(b.text_frame, [{"text": win, "size": 14, "bold": True, "color": "FFFFFF"}], MSO_ANCHOR.MIDDLE,
               margins=(0.15, 0, 0.1, 0))
for k, (kick, body) in enumerate([("Receiver JSON", "Payload goodput, share, and Jain’s index"),
                                  ("TCP socket counters", "Retransmissions per 1,000 outgoing data segments"),
                                  ("Ping and TBF", "P50, P95, and P99 above idle RTT, plus queue backlog")]):
    card(s, L + k * (cw3 + 0.35), 4.3, cw3, 1.7, [kicker(kick), {"text": body, "size": 18, "color": MUTED,
                                                                 "line": 1.1}], name=f"{kick} card")
scope(s, "Validation · 50.30 ms idle RTT · 0.494% measured at 0.5% loss · 75 valid runs")

# 6 Results RQ1
s = new_slide(6, "Results · RQ1", f"BBRv1 kept {retain['bbr']:.0f}% of its goodput at 2% loss")
box(s, L, TOP - 0.05, 8.35, 3.95, name="Chart panel")
loss_chart(s, L + 0.12, TOP + 0.02, 8.1, 3.8)
sx, sw = L + 8.65, CW - 8.65
text(s, sx, TOP - 0.05, sw, 0.35, kicker("At 2% injected loss", MUTED, 13))
for k, cc in enumerate(ALGO):
    name, color, kind = ALGO[cc]
    stat_card(s, sx, TOP + 0.4 + k * 1.18, sw, 1.0, f"{med[(cc, 2.0)]:.2f}", "Mb/s", name, kind, color,
              name=f"{name} stat")
insight(s, "At 0% injected loss, all three exceeded 93 Mb/s. BBRv1 had the lowest P95 excess RTT. "
           "Lines join the medians of five runs.")

# 7 Results RQ2 and RQ3
s = new_slide(7, "Results · RQ2 and RQ3",
              f"A deeper queue evened the split but added {p95[4.0] - p95[0.25]:.0f} ms of P95 delay")
cwq = 4.45
for k, args in enumerate([
        ("bbr_share", 100, 112, 25, ACCENT, "BBR goodput share (%)", lambda v: f"{v:.1f}%",
         "BBRv1 share of goodput", 50, "Share chart"),
        ("excess_rtt_p95", 1, 250, 50, DELAY, "P95 excess RTT (ms)", lambda v: f"{v:.1f}",
         "P95 excess RTT (ms)", None, "Delay chart")]):
    x = L + k * (cwq + 0.25)
    box(s, x, TOP, cwq, 3.85, name=f"{args[-1]} panel")
    queue_chart(s, x + 0.08, TOP + 0.05, cwq - 0.16, 3.75, *args[:8], ref=args[8], name=args[9])
sx = L + 2 * (cwq + 0.25)
sw = CW - (sx - L)
for k, (num, unit, lab) in enumerate([(f"{agg[0.25]:.1f} → {agg[4.0]:.1f}", "Mb/s", "Aggregate goodput"),
                                      (f"{jain[0.25]:.3f} → {jain[4.0]:.3f}", "", "Jain’s index"),
                                      ("0.25 BDP", "", "Most retransmissions, for both flows")]):
    stat_card(s, sx, TOP + k * 1.3, sw, 1.15, num, unit, lab, num_size=22, name=f"{lab} stat")
insight(s, "One BBRv1 flow and one CUBIC flow · five runs per queue size · no injected loss")

# 8 Conclusion
s = new_slide(8, "Conclusion and future work", "Aggregate goodput barely moved; sharing and delay did")
for k, (kick, items) in enumerate([
        ("What the experiment showed",
         ["BBRv1 kept most of its goodput at 2% random loss. CUBIC and Reno each retained below 2%.",
          "At 0.25 BDP, BBRv1 dominated the split and both flows retransmitted most often.",
          f"At 4 BDP, sharing was more even and P95 excess RTT was {p95[4.0] - p95[0.25]:.1f} ms higher "
          "than at 0.25 BDP."]),
        ("Next experiments",
         ["Test intermediate queue sizes with longer overlaps and balanced starts.",
          "Compare a newer BBR version and active queue management on bare-metal Linux."])]):
    card(s, L + k * (cw2 + 0.35), TOP, cw2, 3.75,
         [kicker(kick, space_after=10)] + [{"text": it, "size": 17, "bullet": True, "space_after": 9, "line": 1.05}
                                           for it in items], name=f"{kick} card", pad=0.35)
scope(s, "Scope · BBRv1 · Equal 50 ms base RTTs · One 100 Mb/s drop-tail bottleneck")

# 9 Questions
s = new_slide(9)
t = s.shapes.title
t.left, t.top, t.width, t.height = Inches(L), Inches(2.7), Inches(CW), Inches(1.3)
fill_frame(t.text_frame, [{"text": "Questions?", "size": 66, "bold": True, "align": PP_ALIGN.CENTER}],
           MSO_ANCHOR.MIDDLE)
text(s, L, 4.15, CW, 0.5, {"text": "Hongen Wang · Yuanyu Zhang", "size": 22, "bold": True, "color": MUTED,
                           "align": PP_ALIGN.CENTER})

prs.save(OUT)
print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(prs.slides)} slides)")
