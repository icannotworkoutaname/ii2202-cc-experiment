# II2202 CC experiment: data and analysis handoff

All 75 measurement runs from the research plan are complete and valid
(Part A: 60, Part B: 15), measured on 2026-11-23. This file describes what is in
the repository, how the testbed was set up, how every metric is computed, and
where the setup differs from the research plan.

## 1. Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 analysis/analyze.py            # reads runs/, writes analysis/out/
python3 analysis/pilot_plot.py pilot   # pilot traces -> pilot/pilot_traces.png
python3 analysis/report_figures.py     # report figures -> final_draft/report_source/figures/
```

On Ubuntu, install `python3-venv` first. Checked on 2026-11-23: a fresh venv
(pandas 2.3.3, numpy 2.5.5, scipy 1.18.1, matplotlib 3.11.2) reproduces every CSV
and `.tex` file in `analysis/out/` exactly, in about 10 s.

`analyze.py` takes `--runs <dir>` and `--out <dir>`. It uses only run
directories whose `meta.json` has `"status": "ok"`, so `runs/_failed/` is ignored.
Re-running the analysis needs no root and no testbed; re-running measurements
does (see section 7).

## 2. Repository layout

| Path | Content |
|---|---|
| `testbed/tb.sh` | Creates/removes the namespaces and sets the qdiscs |
| `testbed/run.py` | Run driver: schedule, pilot, Part A/B runs, samplers, run validation |
| `testbed/validate.py` | Validation checks (a)-(f) and host metadata |
| `testbed/params.json` | All experiment parameters (seed, BDP, rates, durations, sampler intervals) |
| `runs/A_<cc>_loss<p>_r<k>/` | Part A runs (cc = bbr/cubic/reno, p = 0/0.1/0.5/2, k = 1..5) |
| `runs/B_q<q>_r<k>/` | Part B runs (q = 0.25/1/4 BDP) |
| `runs/schedule.csv` | Randomised execution order (seed 2202, shuffled within each part) |
| `runs/run_log.csv` | Every attempt with start time, status, duration, max CPU, note |
| `runs/_failed/` | The one voided attempt (section 6) |
| `pilot/` | 3 pilot runs (Part B setup, 0.25/1/4 BDP) and `pilot_traces.png` |
| `validation/20261123-151201/` | Passing validation run (a)-(f), `summary.txt` |
| `validation/20261123-150753/` | Earlier validation run that failed (c), kept as evidence for the GSO fix |
| `docs/host_<ts>/host.txt` | Host metadata at the start of each session (kernel, CPU, tool versions, sysctls, offloads) |
| `analysis/parse.py` | Parsers for one run directory |
| `analysis/analyze.py` | All metrics, tables, tests and figures |
| `analysis/pilot_plot.py` | Pilot figure and 30-s BBR share blocks |
| `analysis/report_figures.py` | The two report figures (`loss-goodput.pdf`, `competition.pdf`) from `analysis/out/*_runs.csv` |
| `analysis/out/` | Generated results (section 5) |

## 3. Testbed

Three Linux network namespaces on one host, connected by veth pairs:

```
snd (10.0.1.1, s0) ── (r0 10.0.1.2) rtr (r1 10.0.2.1) ── (c0 10.0.2.2) rcv
data: snd → rtr → rcv        ACKs: rcv → rtr → snd
```

| Where | qdisc | Purpose |
|---|---|---|
| s0 egress (snd) | `netem loss p% limit 10000` | Random loss on the data path, before the bottleneck. Part A only; installed at 0% too so all Part A conditions use the same qdisc chain |
| r0 egress (rtr → snd) | `netem delay 50ms limit 10000` | Base RTT, placed on the ACK path |
| r1 egress (rtr → rcv) | `tbf rate 100mbit burst 4542 limit Q` | The bottleneck and its queue |

- BDP = 100 Mb/s × 50 ms = 625 000 bytes. Queue limit Q = 1 BDP in Part A and
  0.25 / 1 / 4 BDP (156 250 / 625 000 / 2 500 000 bytes) in Part B.
- TSO, GSO and GRO are off on all four veth ends; `gso_max_segs 1` on s0 and c0
  (section 6).
- `net.ipv4.tcp_no_metrics_save = 1` in snd and rcv; `tcp_rmem` / `tcp_wmem`
  maximum 16 MB; `net.core.rmem_max` / `wmem_max` = 16 MB.
- All three qdiscs are deleted and re-added before every run, so the qdisc
  counters in each run directory start at zero.
- Host: Intel i7-12700H (20 logical CPUs), Windows 11, WSL2 Ubuntu 24.04, kernel
  6.6.87.2-microsoft-standard-WSL2 (BBR v1, `tcp_bbr` module). Tools: iperf 3.16,
  iproute2 6.1.0, ethtool 6.7, sysstat 12.6.1, iputils 20240117.
- Testbed code used for all runs: git commit `5a18ab9`. Each `meta.json` records
  `1415459…`, the hash of the same commit before its message was edited (the files
  are identical). `meta.json` also records `"dirty": true` because analysis files
  were uncommitted at the time; `testbed/` was unchanged.

## 4. Run procedure and raw files

Each run (`testbed/run.py`):

1. Re-create the qdiscs for the condition; save `qdisc_before.txt`.
2. Wait 5 s; save `idle_ping.txt` (20 pings, 0.2 s apart).
3. Start one iperf3 server per flow in rcv (`iperf3 -s -1 -J`, ports 5201, 5202),
   save `nstat_before.txt`, start the samplers.
4. Start the client(s) in snd:
   `iperf3 -c 10.0.2.2 -C <cc> -t <secs> -i 1 -J --get-server-output`.
   Part A: one flow, 120 s. Part B: BBR and CUBIC, 300 s each; the second flow
   starts 5 s after the first. BBR starts first in reps 1, 3, 5 and CUBIC in reps 2, 4.
5. Stop the samplers; save `nstat_after.txt` and `qdisc_after.txt`.
6. Check the run: no iperf3 errors, the kernel used the requested CC
   (`actual_cc`), receiver JSON present, max per-core CPU busy < 50%.
   A failing run is moved to `runs/_failed/<id>_a<n>` and retried (max 3 attempts).

Files per run directory:

| File | Content |
|---|---|
| `meta.json` | Condition, `flows` (cc, server port, `launch_epoch`, `local_port`, `actual_cc`), max CPU, status, git commit, kernel, wall-clock start/end |
| `iperf_<cc>.json` | iperf3 client JSON; receiver-side 1-s intervals in `server_output_json.intervals` |
| `ping.txt` | `ping -D -i 0.01` snd → rcv for the whole run (epoch timestamp per reply) |
| `idle_ping.txt` | 20 pings before the flows start |
| `ss.txt` | `ss -tin dst 10.0.2.2` in snd every 100 ms; each block starts with `# <epoch>` |
| `tc.txt` | `tc -s qdisc show dev r1` every 100 ms; each block starts with `# <epoch>` |
| `cpu.json` | `mpstat -P ALL -o JSON 1` |
| `nstat_before.txt`, `nstat_after.txt` | `nstat -az` in snd |
| `qdisc_before.txt`, `qdisc_after.txt` | `tc -s qdisc` of s0, r0 and r1 |

Time zero of a run (t = 0) is the launch of the first flow (`min(launch_epoch)`).
iperf3 interval offsets are converted to epoch time by adding that flow's
`launch_epoch`.

## 5. Metrics and outputs

Analysis windows: Part A t ∈ (20, 120] s, Part B t ∈ (60, 300] s. The warm-up
lengths were chosen from the pilot runs.

| Metric | Definition |
|---|---|
| Goodput (Mb/s) | Receiver-side bytes of the iperf3 1-s intervals whose end time falls in the window, × 8, divided by the summed interval durations |
| Utilization | Goodput / 100 Mb/s (Part B: aggregate goodput / 100) |
| Retransmissions per 1000 | From `ss` for the flow's data connection (matched on `local_port`): Δ`retrans` total / Δ`data_segs_out` × 1000, between the first and last sample in the window |
| Excess RTT P50/P95/P99 (ms) | Ping RTT minus the median of `idle_ping.txt`, over pings whose send time (reply timestamp − RTT) falls in the window. Pings share the bottleneck queue with the data |
| TBF queueing delay (ms) | `tc` backlog bytes × 8 / 100 Mb/s |
| BBR share | BBR goodput / (BBR + CUBIC goodput) |
| Jain's index | (x₁ + x₂)² / (2 (x₁² + x₂²)) on the two goodputs |
| Steady state (Part B) | BBR share in eight 30-s blocks over 60–300 s; "settled" if the last block is within 0.10 of the first. All metrics are also recomputed over the last 120 s (180–300 s) |
| Tests | Exact two-sided Mann–Whitney U (`scipy.stats.mannwhitneyu`, `method="exact"`), n = 5 per group. The smallest possible p with 5 vs 5 is 2/252 ≈ 0.0079. `ranges_overlap` says whether the two groups' value ranges overlap |

Reference lines in `fig_A.png`: Mathis model with C = 0.93 (random loss, delayed
ACKs; the receiver acknowledged 2.4–2.8 data segments per ACK in the lossy CUBIC and
Reno runs), MSS 1448 B, RTT 50 ms;
"header limit" 95.6 Mb/s = 100 Mb/s × 1448 / 1514 (payload per Ethernet frame).

Files in `analysis/out/`:

| File | Content |
|---|---|
| `A_runs.csv`, `B_runs.csv` | One row per run, all metrics and data-quality columns |
| `A_summary.csv/.tex`, `B_summary.csv/.tex` | Median [Q1, Q3] per condition (LaTeX tabular for the report) |
| `tests.csv` | All hypothesis tests (H1–H3) with medians, U, p, range overlap |
| `steady_state.csv` | Part B 30-s block shares and the last-120-s recompute |
| `fig_A.png` | Part A: goodput (log), retransmissions, excess RTT P50/P95 vs loss |
| `fig_B.png` | Part B: share, Jain, aggregate goodput, retransmissions, delay vs queue size |
| `fig_B_traces.png` | Part B rep 1 per queue size: per-second rates and queueing delay over time |

Selected data-quality columns in `*_runs.csv`: `idle_rtt_ms`, `max_core_busy_pct`,
`ping_samples`, `delay_netem_drops` (drops in the 50 ms netem; must be 0),
`netem_drops_run` (loss netem drops, Part A), `tbf_drops_run`, `nstat_TcpOutSegs`,
`nstat_TcpRetransSegs`, `iperf_retransmits_run`.

## 6. Data quality and deviations from the research plan

Data quality, all 75 valid runs:

- Max per-core CPU busy: ≤ 21.8% (Part A), ≤ 19.2% (Part B); limit 50%.
- Idle RTT: 50.20–50.40 ms.
- Delay netem drops: 0 in every run.
- All 15 Part B runs meet the steady-state rule.
- Validation (a)–(f): all pass (`validation/20261123-151201/summary.txt`), e.g.
  idle RTT 50.30 ms, CUBIC 95.37 Mb/s, netem loss 0.494% for a 0.5% setting.

Deviations:

1. **WSL2 instead of a physical machine.** The plan asks for no VM; WSL2 runs on
   Hyper-V. Validation checks (a)–(f) and the per-run CPU limit are the evidence that
   the VM did not limit the experiment.
2. **`gso_max_segs 1` on s0 and c0.** With GSO off, TCP still hands multi-segment
   skbs to the qdisc and splits them only after it, so netem dropped whole bursts:
   the first validation run measured 0.078% loss for a 0.5% setting
   (`validation/20261123-150753`). Limiting GSO skbs to one segment gives per-packet
   loss (0.494%).
3. **Ping rate.** Requested every 10 ms (100/s); WSL2 delivered 66–80 probes per
   second inside the analysis windows (column `ping_samples`).
4. **Part B start stagger.** The second flow starts 5 s after the first, and the
   first flow alternates between BBR and CUBIC across reps.
5. **Global socket buffer limit.** `net.core.rmem_max` / `wmem_max` are not
   per-namespace, so they were set for the whole WSL2 VM.
6. **One voided attempt.** `A_reno_loss0_r2` attempt 1 reached 100% CPU because an
   analysis process ran on the same VM at the same time. The run driver rejected it
   and the retry passed; the voided data is in `runs/_failed/A_reno_loss0_r2_a1`.
   Every other run passed at the first attempt (`runs/run_log.csv`).

## 7. Re-running measurements

Needs Linux with root, `iproute2`, `iperf3`, `ethtool`, `sysstat`, `iputils-ping`,
and the `tcp_bbr` module. From the repo root:

```bash
sudo python3 testbed/validate.py          # checks (a)-(f)
sudo python3 testbed/run.py run A         # or: run B / pilot / one <run_id>
```

Both scripts tear down and rebuild the testbed themselves (`tb.sh down` + `up`).
Runs whose directory already has `"status": "ok"` are skipped, so to repeat the
measurements work in a fresh clone or move `runs/` aside first. Do not run other
heavy work on the same machine while measuring.
