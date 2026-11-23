#!/usr/bin/env python3
"""Validation checks (a)-(f) for the II2202 testbed. Run as root from the repo root:

    sudo python3 testbed/validate.py [--secs 60]

Writes everything to validation/<timestamp>/ and prints a PASS/FAIL table.

(a) idle RTT: median of 20 pings within 1 ms of 50 ms
(b) one CUBIC flow, no injected loss, 1 BDP queue: receiver goodput >= 93 Mb/s
(c) 0.5% loss on s0: netem drop rate within 0.1 percentage points of 0.5%
    (uses a BBR flow so that enough packets pass for a tight estimate)
(d) the delay netem on r0 reports no drops
(e) ss shows no receive-window limitation for the data connection
(f) per-core CPU busy < 50% during the flows
"""
import argparse, json, re, statistics, subprocess, threading, time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TB = "bash " + str(REPO / "testbed" / "tb.sh")  # via bash: edits over \\wsl$ drop the exec bit
RCV_IP = "10.0.2.2"
BDP = 625_000
PORT = 5201


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True, **kw).stdout


def nsx(ns, cmd):
    return f"ip netns exec {ns} {cmd}"


def qdisc_stats(ns, dev):
    """Return dict(sent_pkts, dropped, backlog_bytes) for the root qdisc of dev."""
    out = sh(nsx(ns, f"tc -s qdisc show dev {dev}"))
    m = re.search(r"Sent (\d+) bytes (\d+) pkt \(dropped (\d+)", out)
    b = re.search(r"backlog (\d+)b", out)
    return {"sent_pkts": int(m.group(2)), "dropped": int(m.group(3)),
            "backlog_bytes": int(b.group(1)) if b else 0, "raw": out}


def idle_rtt(outdir):
    out = sh(nsx("snd", f"ping -c 20 -i 0.2 {RCV_IP}"))
    (outdir / "idle_ping.txt").write_text(out)
    rtts = [float(x) for x in re.findall(r"time=([\d.]+) ms", out)]
    return statistics.median(rtts)


class Sampler:
    """Runs ss every 100 ms in snd and mpstat every 1 s, in the background."""

    def __init__(self, outdir, tag, secs):
        self.ss_path = outdir / f"{tag}_ss.txt"
        self.cpu_path = outdir / f"{tag}_cpu.json"
        self.stop = threading.Event()
        self.secs = secs

    def _ss_loop(self):
        with open(self.ss_path, "w") as f:
            while not self.stop.is_set():
                out = subprocess.run(nsx("snd", f"ss -tin dst {RCV_IP}"), shell=True,
                                     text=True, capture_output=True).stdout
                f.write(f"# {time.time():.3f}\n{out}")
                time.sleep(0.1)

    def __enter__(self):
        self.t = threading.Thread(target=self._ss_loop, daemon=True)
        self.t.start()
        self.cpu = subprocess.Popen(f"mpstat -P ALL -o JSON 1 {self.secs}", shell=True,
                                    stdout=open(self.cpu_path, "w"), text=True)
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.t.join()
        self.cpu.wait()


def run_flow(cc, secs, outdir, tag):
    srv = subprocess.Popen(nsx("rcv", f"iperf3 -s -p {PORT} -1 -J"), shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    with Sampler(outdir, tag, secs):
        out = sh(nsx("snd", f"iperf3 -c {RCV_IP} -p {PORT} -C {cc} -t {secs} -i 1 -J "
                            f"--get-server-output"))
    srv.wait(timeout=10)
    (outdir / f"{tag}_iperf.json").write_text(out)
    return json.loads(out)


def receiver_goodput_mbps(res, skip=10):
    ivs = res["server_output_json"]["intervals"]
    bps = [iv["sum"]["bits_per_second"] for iv in ivs if iv["sum"]["start"] >= skip]
    return statistics.mean(bps) / 1e6


def rwnd_limited_pct(ss_path, local_port):
    """Last reported rwnd_limited % for the data connection (0 if never reported)."""
    pct = 0.0
    block = None
    for line in Path(ss_path).read_text().splitlines():
        if re.search(rf":{local_port}\s", line):
            block = True
            continue
        if block:
            m = re.search(r"rwnd_limited:\d+ms\(([\d.]+)%\)", line)
            pct = float(m.group(1)) if m else pct
            block = None
    return pct


def max_core_busy(cpu_path):
    stats = json.loads(Path(cpu_path).read_text())["sysstat"]["hosts"][0]["statistics"]
    busy = [100 - c["idle"] for s in stats for c in s["cpu-load"] if c["cpu"] != "all"]
    return max(busy)


def host_metadata(outdir):
    cmds = {
        "uname": "uname -a", "lscpu": "lscpu", "modinfo_tcp_bbr": "modinfo tcp_bbr",
        "iperf3": "iperf3 --version", "iproute2": "ip -V",
        "sysctl_snd": nsx("snd", "sysctl net.ipv4.tcp_no_metrics_save net.ipv4.tcp_rmem "
                                 "net.ipv4.tcp_wmem net.ipv4.tcp_congestion_control "
                                 "net.ipv4.tcp_available_congestion_control"),
        "sysctl_root": "sysctl net.core.rmem_max net.core.wmem_max",
    }
    for dev_ns in ["snd:s0", "rtr:r0", "rtr:r1", "rcv:c0"]:
        ns, dev = dev_ns.split(":")
        cmds[f"ethtool_{dev}"] = nsx(ns, f"ethtool -k {dev}")
    with open(outdir / "host.txt", "w") as f:
        for name, cmd in cmds.items():
            f.write(f"===== {name}: {cmd}\n")
            f.write(subprocess.run(cmd, shell=True, text=True, capture_output=True).stdout + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=60)
    args = ap.parse_args()
    outdir = REPO / "validation" / datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True)

    sh(f"{TB} down"); sh(f"{TB} up")
    host_metadata(outdir)
    results = []

    # (a)
    sh(f"{TB} qdisc {BDP} none")
    rtt = idle_rtt(outdir)
    results.append(("a", f"idle RTT median {rtt:.2f} ms", abs(rtt - 50) <= 1))

    # (b) + (e) + (f) on the CUBIC run
    r = run_flow("cubic", args.secs, outdir, "b_cubic")
    gp = receiver_goodput_mbps(r)
    results.append(("b", f"CUBIC receiver goodput {gp:.2f} Mb/s (>= 93)", gp >= 93))
    lport = r["start"]["connected"][0]["local_port"]
    rw = rwnd_limited_pct(outdir / "b_cubic_ss.txt", lport)
    results.append(("e", f"rwnd_limited {rw:.1f}% of time", rw < 1))
    cpu_b = max_core_busy(outdir / "b_cubic_cpu.json")
    d_b = qdisc_stats("rtr", "r0")["dropped"]

    # (c) + (d) + (f) on the lossy BBR run (fresh qdiscs -> counters start at 0)
    sh(f"{TB} qdisc {BDP} 0.5")
    run_flow("bbr", args.secs, outdir, "c_bbr_loss05")
    s0 = qdisc_stats("snd", "s0")
    rate = 100 * s0["dropped"] / (s0["sent_pkts"] + s0["dropped"])
    results.append(("c", f"netem drop rate {rate:.3f}% "
                         f"({s0['dropped']}/{s0['sent_pkts'] + s0['dropped']} pkts)",
                    abs(rate - 0.5) <= 0.1))
    d_c = qdisc_stats("rtr", "r0")["dropped"]
    results.append(("d", f"delay netem drops: {d_b} (b run), {d_c} (c run)", d_b == 0 and d_c == 0))
    cpu_c = max_core_busy(outdir / "c_bbr_loss05_cpu.json")
    cpu = max(cpu_b, cpu_c)
    results.append(("f", f"max per-core busy {cpu:.1f}%", cpu < 50))

    (outdir / "qdisc_final.txt").write_text(sh(f"{TB} show"))
    results.sort()
    lines = [f"({c}) {'PASS' if ok else 'FAIL'}  {msg}" for c, msg, ok in results]
    summary = "\n".join(lines) + f"\n\nALL {'PASS' if all(ok for *_, ok in results) else 'FAIL'}\n"
    (outdir / "summary.txt").write_text(summary)
    print(f"output: {outdir}\n\n{summary}")


if __name__ == "__main__":
    main()
