#!/usr/bin/env bash
# Append a peer to server wg0.conf and hot-add via wg set. Usage: add-peer.sh <PUBKEY> <IP/32> <NAME> <TIER>
set -euo pipefail
PUB="${1:?pubkey}"; IP="${2:?ip}"; NAME="${3:?name}"; TIER="${4:?tier}"
WGCONF="${FILTERVPN_WG_CONF:-/etc/wireguard/wg0.conf}"
{
  echo ""
  echo "[Peer]"
  echo "# $NAME tier=$TIER"
  echo "PublicKey = $PUB"
  echo "AllowedIPs = $IP"
} >> "$WGCONF"
wg set wg0 peer "$PUB" allowed-ips "$IP" || echo "wg set failed (interface down?); peer persisted in $WGCONF"
