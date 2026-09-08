#!/usr/bin/env bash
# Confirm YouTube restrict CNAME chain end-to-end.
set -euo pipefail
for port in 5353 5354; do
  echo "== port $port =="
  for h in www.youtube.com m.youtube.com youtubei.googleapis.com youtube.googleapis.com www.youtube-nocookie.com; do
    printf "%-28s -> " "$h"
    dig +short @127.0.0.1 -p "$port" "$h" | head -2 | tr '\n' ' '; echo
  done
done
