#!/usr/bin/env bash
# Testbed for II2202: snd --(s0|r0)-- rtr --(r1|c0)-- rcv
#
#   data  : snd s0 -> r0 rtr r1 -> c0 rcv
#   ACKs  : rcv c0 -> r1 rtr r0 -> s0 snd
#
#   s0 egress : netem loss p%        (random loss, Part A only)
#   r0 egress : netem delay 50ms     (base RTT, on the ACK path)
#   r1 egress : tbf 100mbit, limit Q (the bottleneck queue)
#
# Usage (as root):
#   tb.sh up                         create namespaces, links, addresses, sysctls
#   tb.sh qdisc <queue_bytes> <loss> set qdiscs; <loss> is a percent (e.g. 0.5) or "none"
#   tb.sh show                       print tc -s qdisc for all three namespaces
#   tb.sh down                       delete everything
#
# Env overrides: RATE (100mbit), DELAY (50ms), BURST (bytes, 4542 = 3 frames)
set -euo pipefail

RATE="${RATE:-100mbit}"
DELAY="${DELAY:-50ms}"
BURST="${BURST:-4542}"
NETEM_LIMIT=10000
SOCKBUF=16777216   # 16 MB

SND_IP=10.0.1.1; RTR_IP0=10.0.1.2
RTR_IP1=10.0.2.1; RCV_IP=10.0.2.2

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }

nsx() { local ns=$1; shift; ip netns exec "$ns" "$@"; }

up() {
  for ns in snd rtr rcv; do ip netns add "$ns"; nsx "$ns" ip link set lo up; done

  ip link add s0 netns snd type veth peer name r0 netns rtr
  ip link add r1 netns rtr type veth peer name c0 netns rcv

  nsx snd ip addr add $SND_IP/24  dev s0
  nsx rtr ip addr add $RTR_IP0/24 dev r0
  nsx rtr ip addr add $RTR_IP1/24 dev r1
  nsx rcv ip addr add $RCV_IP/24  dev c0
  for pair in snd:s0 rtr:r0 rtr:r1 rcv:c0; do
    nsx "${pair%%:*}" ip link set "${pair##*:}" up
  done
  nsx snd ip route add default via $RTR_IP0
  nsx rcv ip route add default via $RTR_IP1
  nsx rtr sysctl -qw net.ipv4.ip_forward=1

  # MTU-sized packets at every qdisc
  for pair in snd:s0 rtr:r0 rtr:r1 rcv:c0; do
    nsx "${pair%%:*}" ethtool -K "${pair##*:}" tso off gso off gro off 2>/dev/null
  done
  # TCP always builds GSO skbs and segments them only *after* the qdisc, so with
  # gso off the s0 netem would still drop multi-segment bursts. Capping the
  # device at 1 segment per skb makes netem loss independent per packet.
  nsx snd ip link set dev s0 gso_max_segs 1
  nsx rcv ip link set dev c0 gso_max_segs 1

  # end hosts: no cached TCP metrics, 16 MB socket buffers
  for ns in snd rcv; do
    nsx "$ns" sysctl -qw net.ipv4.tcp_no_metrics_save=1
    nsx "$ns" sysctl -qw net.ipv4.tcp_rmem="4096 131072 $SOCKBUF"
    nsx "$ns" sysctl -qw net.ipv4.tcp_wmem="4096 16384 $SOCKBUF"
    nsx "$ns" sysctl -qw net.core.rmem_max=$SOCKBUF 2>/dev/null || true
    nsx "$ns" sysctl -qw net.core.wmem_max=$SOCKBUF 2>/dev/null || true
  done
  # net.core.*mem_max may be global rather than per-netns; set it in the root ns too
  sysctl -qw net.core.rmem_max=$SOCKBUF net.core.wmem_max=$SOCKBUF
  echo "testbed up"
}

qdisc() {
  local q=${1:?queue bytes}; local loss=${2:?loss percent or none}
  # delete + add (not replace): replace keeps the old counters for the same qdisc kind
  nsx rtr tc qdisc del dev r1 root 2>/dev/null || true
  nsx rtr tc qdisc del dev r0 root 2>/dev/null || true
  nsx snd tc qdisc del dev s0 root 2>/dev/null || true
  nsx rtr tc qdisc add dev r1 root tbf rate "$RATE" burst "$BURST" limit "$q"
  nsx rtr tc qdisc add dev r0 root netem delay "$DELAY" limit $NETEM_LIMIT
  if [[ $loss != none ]]; then
    nsx snd tc qdisc add dev s0 root netem loss "${loss}%" limit $NETEM_LIMIT
  fi
}

show() {
  for pair in snd:s0 rtr:r0 rtr:r1; do
    echo "== ${pair%%:*} ${pair##*:}"; nsx "${pair%%:*}" tc -s qdisc show dev "${pair##*:}"
  done
}

down() {
  for ns in snd rtr rcv; do ip netns del "$ns" 2>/dev/null || true; done
  echo "testbed down"
}

case "${1:-}" in
  up) up ;;
  qdisc) shift; qdisc "$@" ;;
  show) show ;;
  down) down ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
