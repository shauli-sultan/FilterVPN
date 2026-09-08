#!/usr/bin/env bash
# Verify per-tier DNS behavior from the server (simulates source IPs via @127.0.0.1 ports).
set -euo pipefail
echo "== Tier1 (5351): youtube should resolve normally =="
dig +short @127.0.0.1 -p 5351 www.youtube.com | head -3
echo "== Tier3 (5353): youtube should CNAME restrict.youtube.com =="
dig +short @127.0.0.1 -p 5353 www.youtube.com | head -3
dig @127.0.0.1 -p 5353 www.youtube.com | grep -i restrict || echo "WARN: no restrict CNAME seen"
echo "== Tier4 (5354): tiktok should point at block page (10.100.0.1) =="
dig +short @127.0.0.1 -p 5354 tiktok.com | head -3
echo "== ALL tiers (5351-5354): porn/hentai must point at block page (10.100.0.1) =="
for port in 5351 5352 5353 5354; do
  for d in pornhub.com www.pornhub.com xvideos.com xnxx.com youporn.com nhentai.net; do
    printf "port %s %-16s -> " "$port" "$d"
    dig +short @127.0.0.1 -p "$port" "$d" | head -1
  done
done
echo "== Tier4: youtube still restricted =="
dig +short @127.0.0.1 -p 5354 www.youtube.com | head -3
echo "== Tier1 (5351): google resolves normally =="
dig +short @127.0.0.1 -p 5351 www.google.com | head -2
echo "== Tier3/4: google must CNAME forcesafesearch.google.com =="
for port in 5353 5354; do
  for d in www.google.com www.google.co.il images.google.com; do
    printf "port %s %-20s -> " "$port" "$d"
    dig +short @127.0.0.1 -p "$port" "$d" | head -2 | tr '\n' ' '; echo
  done
done
