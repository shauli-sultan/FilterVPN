# FilterVPN — Scalable Content-Filtering VPN (OCI Always-Free)

WireGuard-based filtering VPN for communities/institutions. One small
Oracle Cloud (Always-Free Ampere A1) server tunnels all client traffic and
enforces **per-tier filtering** based on the client's VPN IP — no per-device
configuration beyond importing a WireGuard profile.

**Stack:** Ubuntu 24.04 ARM · WireGuard · CoreDNS (4 tier instances) ·
iptables + policy routing · Squid `ssl_bump` + Python ICAP worker ·
FastAPI enroll portal.

---

## 1. How it works

```
Phone (WireGuard app, tunnel-all 0.0.0.0/0)
  └─UDP 51820─▶ OCI server, wg0 10.100.0.1/16
       ├─ 10.100.1.x (Tier 1) ─▶ NAT ─▶ CoreDNS:5351 ─▶ internet (direct)
       ├─ 10.100.2.x (Tier 2) ─▶ Squid:3128/3129 ─▶ CoreDNS:5352 ─▶ internet
       ├─ 10.100.3.x (Tier 3) ─▶ Squid ─▶ CoreDNS:5353 (YouTube restricted) ─▶ internet
       └─ 10.100.4.x (Tier 4) ─▶ NAT ─▶ CoreDNS:5354 (YT restricted + social sink)
```

The server maps `10.100.<tier>.x` → firewall rules, DNS instance, and proxy
routing via `routing/pbr.sh` (policy tables 101–104 + iptables DNAT/REDIRECT).
Adding a user = allocating an IP in their tier's pool and adding one
`[Peer]` — filtering follows automatically.

## 2. Filtering tiers

| Tier | Pool | DNS | Behavior |
|------|------|-----|----------|
| **1 Basic** | `10.100.1.0/24` (→`/20`) | :5351 | Porn/hentai/adult + malware/phishing DNS block (71+ base domains, regex apex + subdomains → Hebrew block page). Everything else full speed, direct egress |
| **2 Standard** | `10.100.2.0/24` (→`/20`) | :5352 | Tier 1 + transparent Squid proxy with heuristic image/URL screening (needs Root CA on device) |
| **3 Strict + YouTube** | `10.100.3.0/24` (→`/20`) | :5353 | Tier 2 + YouTube Restricted Mode + Google SafeSearch (CNAMEs → `restrict.youtube.com` / `forcesafesearch.google.com`) |
| **4 Max block** | `10.100.4.0/24` (→`/20`) | :5354 | Tier 3 DNS + TikTok/Instagram/Facebook/Reddit/X/Snapchat sent to the Hebrew block page; direct egress (no proxy) |

Server itself: `10.100.0.1/16` on `wg0`. Each `/24` holds 240+ clients today
(.10–.250) and expands to a `/20` (~4000) without renumbering.

> Design notes: YouTube is enforced as **CNAME to `restrict.youtube.com`**
> (Google's supported method — never a hardcoded IP). Cert-pinned apps
> (YouTube/IG/TikTok) are **DNS-enforced only** and spliced through Squid
> untouched, since MITM breaks them. Realistic capacity on the free shape
> (2 OCPUs / 12 GB) is **~500–600 concurrent tunnels**; scale out with more
> instances past that.

## 3. Repo layout

| Path | Contents |
|------|----------|
| `docs/deploy-ssh.md` | **Start here** — full deploy walkthrough over SSH |
| `deploy/oci-terraform/main.tf` | VCN, A1.Flex 2OCPU/12GB instance, security list (51820/udp, 443, 22) |
| `deploy/cloud-init.yaml` | Packages + `ip_forward` bootstrap |
| `wireguard/` | `wg0.conf.template`, `gen-client.py` (IPAM in `ipam.db`, `.conf` + QR output), `add-peer.sh`, `revoke-peer.sh` |
| `coredns/` | `Corefile.5351`–`5354` (one per tier), `install-coredns.sh`, `update-blocklists.sh`, `gen-block-conf.py`, `blocklists/` domain lists + generated snippets (blocked names → block-page IP) |
| `blockpage/` | Hebrew RTL block-explanation server (`server.py`, `block.html`, systemd unit) — shown instead of a bare connection failure |
| `routing/` | `pbr.sh` (PBR tables, NAT, anti-spoof, inter-tier isolation, DNS DNAT, proxy REDIRECT, DoH/DoT blocks), `rules.v4` baseline |
| `proxy/` | `squid.conf`, `ca/gen-ca.sh` (offline Root CA), `worker/icap_worker.py` (NudeNet image screening + Hebrew blocked-image SVG, URL/page word blocking with news `allowlist.txt`, heuristic fallback), `worker/requirements-ml.txt`, `hebrew-errors/` Squid deny page |
| `portal/` | Hebrew RTL self-service portal (`app.py`: form enroll + `.conf`/QR download, JSON API), `requirements.txt` |
| `tests/` | `test-dns-tiers.sh`, `test-youtube-restrict.sh`, `test-wireguard-load.sh` |

## 4. Deploy

**Full guide → [`docs/deploy-ssh.md`](docs/deploy-ssh.md)** (SSH from Windows:
copy repo with `scp`, then run B→G on the server).

Cheat sheet (on the server, from `~/filtervpn`):

```bash
sudo apt-get install -y wireguard wireguard-tools iptables-persistent squid-openssl python3 qrencode curl dnsutils iproute2
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-filtervpn.conf && sudo sysctl --system

# WireGuard server
umask 077; wg genkey | sudo tee /etc/wireguard/server.key >/dev/null
sudo cat /etc/wireguard/server.key | wg pubkey | sudo tee /etc/wireguard/server.pub
sudo cp wireguard/wg0.conf.template /etc/wireguard/wg0.conf
sudo sed -i "s|__SERVER_PRIVATE_KEY__|$(sudo cat /etc/wireguard/server.key)|" /etc/wireguard/wg0.conf
sudo mkdir -p /opt/filtervpn/routing && sudo cp routing/pbr.sh /opt/filtervpn/routing/ && sudo chmod +x /opt/filtervpn/routing/pbr.sh
sudo systemctl enable --now wg-quick@wg0

# Routing + DNS + proxy
sudo bash routing/pbr.sh up && sudo netfilter-persistent save
sudo bash coredns/install-coredns.sh
sudo bash proxy/ca/gen-ca.sh
sudo cp proxy/squid.conf /etc/squid/squid.conf && sudo systemctl restart squid
nohup python3 proxy/worker/icap_worker.py >/var/log/icap-worker.log 2>&1 &
```

## 5. Onboard / manage users

```bash
# New user (allocates next IP in tier pool, writes .conf + QR png)
export FILTERVPN_SERVER_PUBKEY="$(sudo cat /etc/wireguard/server.pub)"
python3 wireguard/gen-client.py --tier 3 --name student001 --endpoint "<PUBLIC_IP>:51820"

# Activate on live interface
sudo bash wireguard/add-peer.sh "<CLIENT_PUBKEY>" "10.100.3.10/32" student001 3

# Remove a user
sudo bash wireguard/revoke-peer.sh "<CLIENT_PUBKEY>"
```

- Send the user `wireguard/clients/<name>.conf` (or the `.png` QR to scan in
  the WireGuard app) — under a minute to import.
- Tier 2/3 users additionally install `proxy/ca/FilterVPN-RootCA.crt` once
  (Android: Settings → Security → Install certificate; iPhone: trust under
  Settings → General → About → Certificate Trust Settings).
- Optional self-service portal (both manual-share and portal supported):
  `ADMIN_TOKEN=... ENDPOINT=<PUBLIC_IP>:51820 uvicorn portal.app:app --host 127.0.0.1 --port 8000`
  behind Caddy/nginx with TLS; never expose the token endpoint over plain HTTP.

## 6. Verify & operate

```bash
bash tests/test-dns-tiers.sh        # per-tier DNS behavior
bash tests/test-youtube-restrict.sh # all 5 YouTube hosts, tiers 3+4
bash tests/test-wireguard-load.sh   # handshakes + basic connectivity
sudo wg show wg0 latest-handshakes  # live clients
sudo tail -f /var/log/squid/access.log
```

After `git pull` on the server: re-copy `Corefile.*` → restart the four
`coredns@` units, reload squid, re-run `pbr.sh up` (see guide §Updating).

## 7. Limits & gotchas

- **Always-Free = 2 OCPUs / 12 GB** (not 4/24 — that's the max shape size).
- `Out of capacity` on Ampere launch is common: retry another AD/region or
  pilot on E2.1.Micro.
- Idle free instances can be reclaimed: keep traffic alive, snapshot the boot
  volume periodically.
- The ICAP worker is heuristic-only (MIME/URL/size) — a no-ML MVP; tune
  `SUSPICIOUS_URL`/thresholds in `proxy/worker/icap_worker.py` before relying
  on Tier 2 image screening.
- Lock down SSH (port 22) to your IP and use one-time portal tokens to avoid
  an open-signup abuse vector on the single egress IP.
