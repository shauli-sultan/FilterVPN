#!/usr/bin/env bash
# Refresh domain lists from public sources, then regenerate CoreDNS snippets.
# - malware: appends fresh StevenBlack matches (malware|phish|botnet) to domains-malware.txt
# - porn/social: curated by hand in domains-porn.txt / domains-social.txt
#   (too large for a template regex — keep them small and major-only).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
BL="$DIR/blocklists"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts -o "$TMP/hosts" || true
if [ -s "$TMP/hosts" ]; then
  grep -E '^0\.0\.0\.0 ' "$TMP/hosts" | awk '{print $2}' | grep -Ei 'malware|phish|botnet' | sort -u > "$TMP/mal" || true
  { grep -v '^#' "$BL/domains-malware.txt" 2>/dev/null || true; cat "$TMP/mal"; } \
    | grep . | sort -u > "$TMP/merged" || true
  { grep '^#' "$BL/domains-malware.txt" 2>/dev/null || true; cat "$TMP/merged"; } > "$BL/domains-malware.txt"
  echo "domains-malware.txt refreshed ($(grep -vc '^#' "$BL/domains-malware.txt") domains)"
else
  echo "fetch failed; keeping existing lists"
fi

python3 "$DIR/gen-block-conf.py"
echo "Done. Restart tiers: systemctl restart coredns@5351 coredns@5352 coredns@5353 coredns@5354"
