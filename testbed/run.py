#!/usr/bin/env python3
"""Run driver for the II2202 experiment. Run as root from the repo root.

    sudo python3 testbed/run.py schedule          # write runs/schedule.csv (seeded order)
    sudo python3 testbed/run.py pilot             # 3 Part B runs (0.25/1/4 BDP) into pilot/
    sudo python3 testbed/run.py run A [--limit N] # Part A runs not yet done, in schedule order
    sudo python3 testbed/run.py run B [--limit N]
    sudo python3 testbed/run.py one <run_id>      # a single run from the schedule

Each run directory holds:
  meta.json          condition, flows, start times, attempt, git commit, status
  qdisc_before.txt / qdisc_after.txt   tc -s qdisc of s0, r0, r1
  idle_ping.txt      20 pings at 0.2 s before the flows start
  ping.txt           ping -D every 10 ms during the run (epoch timestamps)
  ss.txt             ss -tin every 100 ms, each block headed by "# <epoch>"
  tc.txt             tc -s qdisc dev r1 every 100 ms, each block headed by "# <epoch>"
  cpu.json           mpstat -P ALL every 1 s
  nstat_before.txt / nstat_after.txt   absolute TCP counters in snd
  iperf_<cc>.json    iperf3 client JSON incl. receiver-side server_output_json
A run is complete when meta.json has "status": "ok". Rerunning skips complete runs.
"""
import argparse, csv, json, os, random, shutil, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import host_metadata, max_core_busy  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
P = json.loads((REPO / "testbed" / "params.json").read_text())
TB = "bash " + str(REPO / "testbed" / "tb.sh")
RCV_IP = "10.0.2.2"
BASE_PORT = 5201
TB_ENV = {**os.environ, "RATE": P["tb"]["rate"], "DELAY": P["tb"]["delay"],
          "BURST": str(P["tb"]["burst"])}


def sh(cmd):
    return subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True,
                          env=TB_ENV).stdout


def nsx(ns, cmd):
    return f"ip netns exec {ns} {cmd}"


def fmt(x):
    return f"{x:g}"


# ---------------------------------------------------------------- schedule
def build_schedule():
    rng = random.Random(P["seed"])
    a, b = [], []
    A = P["partA"]
    for cc in A["ccs"]:
        for loss in A["loss_pct"]:
            for rep in range(1, P["reps"] + 1):
                a.append({"run_id": f"A_{cc}_loss{fmt(loss)}_r{rep}", "part": "A",
                          "ccs": cc, "loss_pct": loss, "queue_bdp": A["queue_bdp"],
                          "rep": rep, "secs": A["secs"]})
    B = P["partB"]
    for q in B["queue_bdp"]:
        for rep in range(1, P["reps"] + 1):
            order = "bbr,cubic" if rep in B["bbr_first_reps"] else "cubic,bbr"
            b.append({"run_id": f"B_q{fmt(q)}_r{rep}", "part": "B", "ccs": order,
                      "loss_pct": "none", "queue_bdp": q, "rep": rep, "secs": B["secs"]})
    rng.shuffle(a)
    rng.shuffle(b)
    rows = a + b
    for i, r in enumerate(rows, 1):
        r["order"] = i
    return rows


def write_schedule():
    rows = build_schedule()
    path = REPO / "runs" / "schedule.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path, rows


def load_schedule():
    path = REPO / "runs" / "schedule.csv"
    if not path.exists():
        write_schedule()
    with open(path) as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- samplers
class PeriodicSampler(threading.Thread):
    def __init__(self, cmd, path, interval):
        super().__init__(daemon=True)
        self.cmd, self.path, self.interval = cmd, path, interval
        self.stop_ev = threading.Event()

    def run(self):
        nxt = time.time()
        with open(self.path, "w") as f:
            while not self.stop_ev.is_set():
                ts = time.time()
                out = subprocess.run(self.cmd, shell=True, text=True,
                                     capture_output=True).stdout
                f.write(f"# {ts:.3f}\n{out}")
                nxt += self.interval
                time.sleep(max(0.0, nxt - time.time()))

    def stop(self):
        self.stop_ev.set()
        self.join()


def git_info():
    def g(cmd):
        r = subprocess.run(f"git -C {REPO} {cmd}", shell=True, text=True, capture_output=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"commit": g("rev-parse HEAD"), "dirty": bool(g("status --porcelain"))}


def qdisc_snapshot():
    return sh(f"{TB} show")


# ---------------------------------------------------------------- one run
def do_run(row, outdir, attempt):
    ccs = row["ccs"].split(",")
    secs = int(row["secs"])
    stagger = P["partB"]["stagger_s"] if len(ccs) > 1 else 0
    q_bytes = int(round(float(row["queue_bdp"]) * P["bdp_bytes"]))
    loss = row["loss_pct"]
    total = secs + stagger * (len(ccs) - 1)
    S = P["samplers"]

    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    meta = {**row, "queue_bytes": q_bytes, "stagger_s": stagger, "attempt": attempt,
            "tb": P["tb"], "seed": P["seed"], "git": git_info(),
            "kernel": os.uname().release, "status": "running",
            "wall_start": datetime.now().isoformat(timespec="seconds")}

    # 1. fresh qdiscs (counters start at 0)
    sh(f"{TB} qdisc {q_bytes} {loss}")
    (outdir / "qdisc_before.txt").write_text(qdisc_snapshot())

    # 2. settle, then idle RTT
    time.sleep(P["settle_s"])
    (outdir / "idle_ping.txt").write_text(sh(nsx("snd", f"ping -D -c 20 -i 0.2 {RCV_IP}")))

    # 3. servers, counters, samplers
    servers = []
    for i, _ in enumerate(ccs):
        servers.append(subprocess.Popen(
            nsx("rcv", f"iperf3 -s -p {BASE_PORT + i} -1 -J"), shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1)
    (outdir / "nstat_before.txt").write_text(sh(nsx("snd", "nstat -az")))

    ping = subprocess.Popen(
        nsx("snd", f"ping -D -i {S['ping_interval_s']} -w {total + 2} {RCV_IP}"),
        shell=True, stdout=open(outdir / "ping.txt", "w"), stderr=subprocess.STDOUT)
    cpu = subprocess.Popen(f"mpstat -P ALL -o JSON 1 {total + 2}", shell=True,
                           stdout=open(outdir / "cpu.json", "w"))
    ss = PeriodicSampler(nsx("snd", f"ss -tin dst {RCV_IP}"), outdir / "ss.txt",
                         S["ss_interval_s"])
    tc = PeriodicSampler(nsx("rtr", "tc -s qdisc show dev r1"), outdir / "tc.txt",
                         S["tc_interval_s"])
    ss.start(); tc.start()
    time.sleep(1)

    # 4. clients (staggered in Part B)
    clients, flows = [], []
    for i, cc in enumerate(ccs):
        if i:
            time.sleep(stagger)
        t0 = time.time()
        f = open(outdir / f"iperf_{cc}.json", "w")
        clients.append((cc, f, subprocess.Popen(
            nsx("snd", f"iperf3 -c {RCV_IP} -p {BASE_PORT + i} -C {cc} -t {secs} -i 1 -J "
                       f"--get-server-output"),
            shell=True, stdout=f, stderr=subprocess.PIPE, text=True)))
        flows.append({"cc": cc, "port": BASE_PORT + i, "launch_epoch": round(t0, 3)})

    errors = []
    for cc, f, p in clients:
        _, err = p.communicate()
        f.close()
        if p.returncode != 0:
            errors.append(f"iperf3 {cc} exit {p.returncode}: {err.strip()[:200]}")
    for s in servers:
        try:
            s.wait(timeout=10)
        except subprocess.TimeoutExpired:
            s.kill()

    # 5. stop samplers, final counters
    ss.stop(); tc.stop()
    ping.wait(); cpu.wait()
    (outdir / "nstat_after.txt").write_text(sh(nsx("snd", "nstat -az")))
    (outdir / "qdisc_after.txt").write_text(qdisc_snapshot())

    for fl in flows:
        try:
            r = json.loads((outdir / f"iperf_{fl['cc']}.json").read_text())
            if "error" in r:
                errors.append(f"iperf3 {fl['cc']}: {r['error']}")
            fl["iperf_start_epoch"] = r["start"]["timestamp"]["timesecs"]
            fl["local_port"] = r["start"]["connected"][0]["local_port"]
            fl["actual_cc"] = r["end"].get("sender_tcp_congestion")
            if fl["actual_cc"] != fl["cc"]:
                errors.append(f"asked for {fl['cc']}, got {fl['actual_cc']}")
            if "server_output_json" not in r:
                errors.append(f"no receiver JSON for {fl['cc']}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"cannot read iperf_{fl['cc']}.json: {e}")

    busy = max_core_busy(outdir / "cpu.json")
    if busy >= P["max_core_busy_pct"]:
        errors.append(f"CPU {busy:.1f}% >= {P['max_core_busy_pct']}%")

    meta.update(flows=flows, max_core_busy_pct=round(busy, 1), errors=errors,
                wall_end=datetime.now().isoformat(timespec="seconds"),
                status="ok" if not errors else "failed")
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def is_done(outdir):
    m = outdir / "meta.json"
    return m.exists() and json.loads(m.read_text()).get("status") == "ok"


def log(line):
    with open(REPO / "runs" / "run_log.csv", "a") as f:
        f.write(line + "\n")


def run_with_retries(row, base):
    outdir = base / row["run_id"]
    for attempt in range(1, P["max_attempts"] + 1):
        t = time.time()
        meta = do_run(row, outdir, attempt)
        note = "; ".join(meta["errors"])
        log(f"{meta['wall_start']},{row['run_id']},{attempt},{meta['status']},"
            f"{time.time() - t:.0f}s,{meta['max_core_busy_pct']},\"{note}\"")
        print(f"  {row['run_id']} attempt {attempt}: {meta['status']} "
              f"({time.time() - t:.0f} s, CPU {meta['max_core_busy_pct']}%) {note}", flush=True)
        if meta["status"] == "ok":
            return True
        failed = base / "_failed" / f"{row['run_id']}_a{attempt}"
        failed.parent.mkdir(exist_ok=True)
        shutil.move(str(outdir), failed)
    return False


def chown_to_user(*paths):
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid:
        for p in paths:
            subprocess.run(f"chown -R {uid}:{gid} {p}", shell=True)


def session_start(base):
    base.mkdir(exist_ok=True)
    sh(f"{TB} down")
    sh(f"{TB} up")
    hd = REPO / "docs" / f"host_{datetime.now():%Y%m%d-%H%M%S}"
    hd.mkdir(parents=True)
    host_metadata(hd)
    if not (REPO / "runs" / "run_log.csv").exists():
        log("wall_start,run_id,attempt,status,duration,max_core_busy_pct,note")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schedule")
    sub.add_parser("pilot")
    r = sub.add_parser("run"); r.add_argument("part", choices=["A", "B"])
    r.add_argument("--limit", type=int)
    o = sub.add_parser("one"); o.add_argument("run_id")
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("run as root")
    (REPO / "runs").mkdir(exist_ok=True)

    try:
        if args.cmd == "schedule":
            path, rows = write_schedule()
            print(f"{path}: {len(rows)} runs")
        elif args.cmd == "pilot":
            base = REPO / "pilot"
            session_start(base)
            for q in P["partB"]["queue_bdp"]:
                row = {"run_id": f"pilot_B_q{fmt(q)}", "part": "pilot", "ccs": "bbr,cubic",
                       "loss_pct": "none", "queue_bdp": q, "rep": 0,
                       "secs": P["partB"]["secs"], "order": 0}
                run_with_retries(row, base)
        else:
            rows = load_schedule()
            if args.cmd == "one":
                rows = [x for x in rows if x["run_id"] == args.run_id]
            else:
                rows = [x for x in rows if x["part"] == args.part]
            base = REPO / "runs"
            todo = [x for x in rows if not is_done(base / x["run_id"])]
            if getattr(args, "limit", None):
                todo = todo[:args.limit]
            print(f"{len(todo)} runs to do", flush=True)
            session_start(base)
            for x in todo:
                run_with_retries(x, base)
    finally:
        chown_to_user(REPO / "runs", REPO / "pilot", REPO / "docs")


if __name__ == "__main__":
    main()
