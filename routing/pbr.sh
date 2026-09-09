#!/usr/bin/env bash
# Policy-based routing + NAT for tier pools. Usage: pbr.sh up|down
# Tables 101-104 map to tiers 1-4. Requires: iproute2, iptables.
set -euo pipefail
MODE="${1:-up}"
WAN="${WAN_IF:-enp0s3}"
if ! ip link show "$WAN" >/dev/null 2>&1; then
  WAN="$(ip route show default | awk '{print $5; exit}')"
fi

hook_tables() {
  grep -q "101 tier1" /etc/iproute2/rt_tables || echo "101 tier1" >> /etc/iproute2/rt_tables
  grep -q "102 tier2" /etc/iproute2/rt_tables || echo "102 tier2" >> /etc/iproute2/rt_tables
  grep -q "103 tier3" /etc/iproute2/rt_tables || echo "103 tier3" >> /etc/iproute2/rt_tables
  grep -q "104 tier4" /etc/iproute2/rt_tables || echo "104 tier4" >> /etc/iproute2/rt_tables
}

if [ "$MODE" = up ]; then
  hook_tables
  GW="$(ip route show default | awk '{print $3; exit}')"
  for t in 1 2 3 4; do
    n=$((100 + t))
    ip route replace default via "$GW" dev "$WAN" table "$n" 2>/dev/null || true
    # Idempotent rule add: delete if exists, then add (or check)
    if ! ip rule show | grep -q "from 10.100.${t}.0/24.*table $n"; then
      ip rule add from "10.100.${t}.0/24" table "$n" priority "$((1000 + t))" 2>/dev/null || true
    fi
  done
  # NAT + forwarding
  iptables -t nat -C POSTROUTING -s 10.100.0.0/16 -o "$WAN" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s 10.100.0.0/16 -o "$WAN" -j MASQUERADE
  iptables -C FORWARD -i wg0 -o "$WAN" -s 10.100.0.0/16 -m conntrack --ctstate NEW,ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i wg0 -o "$WAN" -s 10.100.0.0/16 -m conntrack --ctstate NEW,ESTABLISHED,RELATED -j ACCEPT
  iptables -C FORWARD -i "$WAN" -o wg0 -d 10.100.0.0/16 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$WAN" -o wg0 -d 10.100.0.0/16 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -C FORWARD -i wg0 ! -s 10.100.0.0/16 -j DROP 2>/dev/null || \
    iptables -A FORWARD -i wg0 ! -s 10.100.0.0/16 -j DROP
  for a in 1 2 3 4; do for b in 1 2 3 4; do
    [ "$a" != "$b" ] && iptables -C FORWARD -s "10.100.${a}.0/24" -d "10.100.${b}.0/24" -j DROP 2>/dev/null || \
      ([ "$a" != "$b" ] && iptables -A FORWARD -s "10.100.${a}.0/24" -d "10.100.${b}.0/24" -j DROP || true)
  done; done
  # MSS must be 1380 for wg MTU 1420 (1420-40), not PMTU (9000 on OCI gives 8960 → drops)
  iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1380 2>/dev/null || \
    iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1380
  # ARM offloading: Oracle VNIC GRO/GSO breaks WireGuard throughput (70→33 KiB/s)
  ethtool -K "$WAN" gro off gso off tso off 2>/dev/null || true
  ethtool -K "$WAN" rx-gro-hw off 2>/dev/null || true
  # Per-tier DNS hijack -> local CoreDNS ports (both UDP and TCP)
  for proto in udp tcp; do
    iptables -t nat -C PREROUTING -i wg0 -s 10.100.1.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5351 2>/dev/null || \
      iptables -t nat -A PREROUTING -i wg0 -s 10.100.1.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5351
    iptables -t nat -C PREROUTING -i wg0 -s 10.100.2.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5352 2>/dev/null || \
      iptables -t nat -A PREROUTING -i wg0 -s 10.100.2.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5352
    iptables -t nat -C PREROUTING -i wg0 -s 10.100.3.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5353 2>/dev/null || \
      iptables -t nat -A PREROUTING -i wg0 -s 10.100.3.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5353
    iptables -t nat -C PREROUTING -i wg0 -s 10.100.4.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5354 2>/dev/null || \
      iptables -t nat -A PREROUTING -i wg0 -s 10.100.4.0/24 -p $proto --dport 53 -j DNAT --to-destination 127.0.0.1:5354
  done
  # Proxy completely removed - DNS only. No REDIRECT to squid. Keep commented for reference.
  # Block common DoH endpoints + DoT to force tier DNS
  for doh in 1.1.1.1 8.8.8.8 9.9.9.9; do
    iptables -C FORWARD -i wg0 -d "$doh" -p tcp --dport 443 -j DROP 2>/dev/null || \
      iptables -A FORWARD -i wg0 -d "$doh" -p tcp --dport 443 -j DROP
  done
  iptables -C FORWARD -i wg0 -p tcp --dport 853 -j DROP 2>/dev/null || \
    iptables -A FORWARD -i wg0 -p tcp --dport 853 -j DROP
  echo "pbr up done (WAN=$WAN)"
else
  # Graceful down: remove rules/routes we added
  for t in 1 2 3 4; do
    n=$((100 + t))
    ip rule del from "10.100.${t}.0/24" table "$n" 2>/dev/null || true
    ip route flush table "$n" 2>/dev/null || true
  done
  echo "pbr down done"
fi
