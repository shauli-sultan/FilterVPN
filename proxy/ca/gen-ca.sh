#!/usr/bin/env bash
# Generate offline Root CA + Squid dynamic cert bundle. Install FilterVPN-RootCA.crt on each device ONCE.
set -euo pipefail
CADIR="${CADIR:-$(dirname "$0")}"
mkdir -p "$CADIR" /var/lib/ssl_db
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout "$CADIR/FilterVPN-RootCA.key" -out "$CADIR/FilterVPN-RootCA.crt" \
  -subj "/CN=FilterVPN Local Root CA/O=Community Filtering"
cat "$CADIR/FilterVPN-RootCA.crt" "$CADIR/FilterVPN-RootCA.key" > "$CADIR/squid-dynamic.pem"
chmod 600 "$CADIR/squid-dynamic.pem" "$CADIR/FilterVPN-RootCA.key"
/usr/lib/squid/security_file_certgen -c -s /var/lib/ssl_db -M 16MB || true
chown -R proxy:proxy /var/lib/ssl_db "$CADIR/squid-dynamic.pem" 2>/dev/null || true
echo "CA ready: $CADIR/FilterVPN-RootCA.crt (distribute to Tier 2/3 devices)"
