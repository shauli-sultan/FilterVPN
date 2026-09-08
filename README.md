# FilterVPN — Scalable Filtering VPN (OCI Always-Free)

Ubuntu 24.04 ARM + WireGuard + CoreDNS (4 tier instances) + Squid ssl_bump + Python ICAP worker.

## Layout

- `deploy/oci-terraform/` — VCN, A1.Flex 2OCPU/12GB instance, security list, cloud-init hookup
- `deploy/cloud-init.yaml` — sysctl, packages, systemd units bootstrap
- `wireguard/` — server template + `gen-client.py` IPAM (sqlite) + add/revoke scripts
- `coredns/` — `Corefile.5351..5354` (Tier 1..4) + blocklist puller
- `routing/` — `pbr.sh` + `rules.v4` (iptables-persistent)
- `proxy/` — `squid.conf`, `ca/gen-ca.sh`, `worker/icap_worker.py`
- `portal/` — FastAPI self-service (wraps gen-client.py) + manual-share output
- `tests/` — DNS tier checks, YouTube restrict check, WireGuard load smoke test

## Subnets (10.100.0.0/16)

| Tier | Pool | DNS port | Path |
|------|------|----------|------|
| 1 Basic | 10.100.1.0/24 (→/20) | 5351 | direct egress |
| 2 Standard | 10.100.2.0/24 (→/20) | 5352 | via Squid |
| 3 Strict+YT | 10.100.3.0/24 (→/20) | 5353 | via Squid + YT restrict CNAME |
| 4 Max block | 10.100.4.0/24 (→/20) | 5354 | direct + social NXDOMAIN |

Server: `10.100.0.1/16` on `wg0`.

## Quick start (on the OCI instance)

```bash
sudo bash deploy/cloud-init.yaml  # or apply via Terraform user_data
sudo bash routing/pbr.sh
sudo bash coredns/install-coredns.sh
sudo bash proxy/ca/gen-ca.sh
sudo systemctl restart wg-quick@wg0 coredns@5351 coredns@5352 coredns@5353 coredns@5354 squid
python3 wireguard/gen-client.py --tier 3 --name student001 --endpoint <PUBLIC_IP>:51820
```

Portal: `uvicorn portal.app:app --host 127.0.0.1 --port 8000` behind nginx/caddy with admin token.

## Notes

- Always-Free quota = 2 OCPUs / 12 GB total. Target ~500-600 concurrent tunnels on one box.
- YouTube enforcement = CNAME to `restrict.youtube.com` (never a hardcoded IP).
- Pinned apps (YouTube/IG/TikTok) are DNS-enforced only, excluded from ssl_bump.
