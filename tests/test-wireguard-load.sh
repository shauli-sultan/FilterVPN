#!/usr/bin/env bash
# Smoke test: handshakes + ping through wg0. Run on server.
set -euo pipefail
wg show wg0 | head -20
echo "--- peers: $(wg show wg0 peers | wc -l)"
ping -c2 -W2 10.100.0.1
echo "OK"
