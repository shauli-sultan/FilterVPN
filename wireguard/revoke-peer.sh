#!/usr/bin/env bash
# Remove a peer by public key. Usage: revoke-peer.sh <PUBKEY>
set -euo pipefail
PUB="${1:?pubkey}"
WGCONF="${FILTERVPN_WG_CONF:-/etc/wireguard/wg0.conf}"
wg set wg0 peer "$PUB" remove || true
python3 - "$WGCONF" "$PUB" <<'EOF'
import sys
path, pub = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines(keepends=True)
out, skip = [], False
for i, ln in enumerate(lines):
    if ln.strip().startswith("[Peer]"):
        block = "".join(lines[i:i+5])
        skip = pub in block
        if not skip:
            out.append(ln)
        continue
    if skip:
        if f"PublicKey = {pub}" in ln or ln.strip().startswith("AllowedIPs") or ln.strip().startswith("#"):
            continue
        skip = False
    out.append(ln)
open(path, "w").writelines(out)
EOF
echo "Revoked $PUB"
