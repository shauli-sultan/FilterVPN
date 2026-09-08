#!/usr/bin/env bash
# Install 4 CoreDNS systemd instances (ports 5351-5354). Run on server.
set -euo pipefail
BIN=/usr/local/bin/coredns
if [ ! -x "$BIN" ]; then
  echo "Installing coredns..."
  VER="1.11.3"
  curl -fsSL "https://github.com/coredns/coredns/releases/download/v${VER}/coredns_${VER}_linux_arm64.tgz" -o /tmp/coredns.tgz
  tar -xzf /tmp/coredns.tgz -C /usr/local/bin coredns
  chmod +x "$BIN"
fi
mkdir -p /opt/filtervpn/coredns
cp -r "$(dirname "$0")"/* /opt/filtervpn/coredns/ 2>/dev/null || cp -r ./coredns/* /opt/filtervpn/coredns/ || true
python3 /opt/filtervpn/coredns/gen-block-conf.py 2>/dev/null || python3 "$(dirname "$0")/gen-block-conf.py" || true
for port in 5351 5352 5353 5354; do
cat > "/etc/systemd/system/coredns@${port}.service" <<EOF
[Unit]
Description=CoreDNS tier instance ${port}
After=network.target
[Service]
ExecStart=$BIN -conf /opt/filtervpn/coredns/Corefile.${port}
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now "coredns@${port}" || true
done
echo "CoreDNS tier instances started"
