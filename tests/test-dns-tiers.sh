#!/usr/bin/env bash
# Verify per-tier DNS behavior from the server (simulates source IPs via @127.0.0.1 ports).
set -euo pipefail
echo "== Tier1 (5351): youtube should resolve normally =="
dig +short @127.0.0.1 -p 5351 www.youtube.com | head -3
echo "== Tier3 (5353): youtube should CNAME restrict.youtube.com =="
dig +short @127.0.0.1 -p 5353 www.youtube.com | head -3
dig @127.0.0.1 -p 5353 www.youtube.com | grep -i restrict || echo "WARN: no restrict CNAME seen"
echo "== Tier4 (5354): tiktok should be sunk (0.0.0.0) =="
dig +short @127.0.0.1 -p 5354 tiktok.com | head -3
echo "== Tier4: youtube still restricted =="
dig +short @127.0.0.1 -p 5354 www.youtube.com | head -3
