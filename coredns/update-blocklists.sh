#!/usr/bin/env bash
# Refresh blocklist zone files from public sources. Edit SOURCES to taste.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/blocklists" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Example: StevenBlack hosts (ads+porn fenced to extreme subset manually) + oisd small
curl -fsSL https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts -o "$TMP/hosts" || true

zone_header() { # $1 origin
  printf '$ORIGIN %s.\n@   IN SOA ns1.admin. admin. (1 7200 3600 1209600 60)\n    IN NS  localhost.\n' "$1"
}
{
  zone_header malware.local
  grep -E '^0\.0\.0\.0 ' "$TMP/hosts" | awk '{print $2}' | grep -Ei 'malware|phish|botnet' | sort -u | awk '{print $1"    IN A 0.0.0.0"}' || true
} > "$DIR/malware.db"
{
  zone_header adult.local
  grep -E '^0\.0\.0\.0 ' "$TMP/hosts" | awk '{print $2}' | grep -Ei 'porn|xxx|sex' | head -500 | sort -u | awk '{print $1"    IN A 0.0.0.0"}' || true
} > "$DIR/adult.db"
echo "Refreshed malware.db + adult.db (social.db is curated manually)"
