"""Parsers for one run directory. All time series use absolute epoch seconds in
column "epoch"; callers convert to run time with t = epoch - t0(meta)."""
import json, re
from pathlib import Path

import pandas as pd

LINK_BPS = 100e6


def meta(d):
    return json.loads((Path(d) / "meta.json").read_text())


def t0(m):
    """Run time zero = launch of the first flow."""
    return min(f["launch_epoch"] for f in m["flows"])


def iperf(d, cc):
    return json.loads((Path(d) / f"iperf_{cc}.json").read_text())


def receiver_intervals(d, m, cc):
    """One row per 1-s receiver interval: epoch_start, epoch_end, bytes, mbps."""
    flow = next(f for f in m["flows"] if f["cc"] == cc)
    ivs = iperf(d, cc)["server_output_json"]["intervals"]
    rows = [{"epoch_start": flow["launch_epoch"] + iv["sum"]["start"],
             "epoch_end": flow["launch_epoch"] + iv["sum"]["end"],
             "bytes": iv["sum"]["bytes"],
             "mbps": iv["sum"]["bits_per_second"] / 1e6} for iv in ivs]
    return pd.DataFrame(rows)


def sender_summary(d, cc):
    e = iperf(d, cc)["end"]
    return {"retransmits": e["sum_sent"]["retransmits"], "bytes_sent": e["sum_sent"]["bytes"]}


_PING = re.compile(r"^\[([\d.]+)\] \d+ bytes from .*icmp_seq=(\d+) .*time=([\d.]+) ms")


def ping(d, name="ping.txt"):
    rows = []
    for line in (Path(d) / name).read_text().splitlines():
        mt = _PING.match(line)
        if mt:
            rows.append((float(mt.group(1)), int(mt.group(2)), float(mt.group(3))))
    df = pd.DataFrame(rows, columns=["epoch", "seq", "rtt_ms"])
    # the -D stamp is the receive time; the probe saw the network when it was sent
    df["epoch"] = df["epoch"] - df["rtt_ms"] / 1000
    return df


def idle_rtt_ms(d):
    return float(ping(d, "idle_ping.txt")["rtt_ms"].median())


def _blocks(path):
    """Yield (epoch, text) for files written as '# <epoch>\\n<output>'."""
    epoch, buf = None, []
    for line in Path(path).read_text().splitlines():
        if line.startswith("# ") and re.fullmatch(r"# [\d.]+", line):
            if epoch is not None:
                yield epoch, "\n".join(buf)
            epoch, buf = float(line[2:]), []
        else:
            buf.append(line)
    if epoch is not None:
        yield epoch, "\n".join(buf)


def tbf(d):
    """TBF on r1 every 100 ms: backlog_bytes, backlog_pkts, dropped, sent_pkts, qdelay_ms."""
    rows = []
    for ep, txt in _blocks(Path(d) / "tc.txt"):
        s = re.search(r"Sent (\d+) bytes (\d+) pkt \(dropped (\d+)", txt)
        b = re.search(r"backlog (\d+)b (\d+)p", txt)
        if s and b:
            rows.append((ep, int(b.group(1)), int(b.group(2)), int(s.group(3)), int(s.group(2))))
    df = pd.DataFrame(rows, columns=["epoch", "backlog_bytes", "backlog_pkts", "dropped",
                                     "sent_pkts"])
    df["qdelay_ms"] = df["backlog_bytes"] * 8 / LINK_BPS * 1000
    return df


_SS_FIELDS = {
    "cwnd": r"\bcwnd:(\d+)", "ss_rtt_ms": r"\brtt:([\d.]+)/", "bytes_acked": r"bytes_acked:(\d+)",
    "data_segs_out": r"data_segs_out:(\d+)", "retrans_total": r"retrans:\d+/(\d+)",
    "delivery_rate": r"delivery_rate (\d+)bps", "pacing_rate": r"pacing_rate (\d+)bps",
}


def ss(d, m):
    """ss -tin samples for the data connections only (matched on iperf3 local_port)."""
    ports = {str(f["local_port"]): f["cc"] for f in m["flows"]}
    rows = []
    for ep, txt in _blocks(Path(d) / "ss.txt"):
        lines = txt.splitlines()
        for i, line in enumerate(lines):
            mt = re.search(r":(\d+)\s+10\.0\.2\.2:\d+", line)
            if mt and mt.group(1) in ports and i + 1 < len(lines):
                info = lines[i + 1]
                row = {"epoch": ep, "cc": ports[mt.group(1)]}
                for k, rx in _SS_FIELDS.items():
                    v = re.search(rx, info)
                    row[k] = float(v.group(1)) if v else None
                rows.append(row)
    return pd.DataFrame(rows)


def nstat_delta(d):
    def read(name):
        out = {}
        for line in (Path(d) / name).read_text().splitlines():
            p = line.split()
            if len(p) >= 2 and p[1].isdigit():
                out[p[0]] = int(p[1])
        return out
    a, b = read("nstat_before.txt"), read("nstat_after.txt")
    return {k: b.get(k, 0) - a.get(k, 0) for k in ("TcpOutSegs", "TcpRetransSegs")}


def qdisc_counters(d, name="qdisc_after.txt"):
    """Dropped / sent packets per device from a 'tb.sh show' snapshot."""
    out, dev = {}, None
    for line in (Path(d) / name).read_text().splitlines():
        h = re.match(r"== \w+ (\w+)", line)
        if h:
            dev = h.group(1)
            continue
        s = re.search(r"Sent \d+ bytes (\d+) pkt \(dropped (\d+)", line)
        if s and dev:
            out[dev] = {"sent_pkts": int(s.group(1)), "dropped": int(s.group(2))}
    return out
