# FilterVPN — DNS-Based Content-Filtering VPN for the Jewish Community (OCI Always-Free)

WireGuard VPN that filters by DNS per tier. One small Oracle Cloud (Always-Free Ampere A1, `il-jerusalem-1`) tunnels all client traffic and enforces **per-tier DNS filtering** based on the client's VPN IP (`10.100.<tier>.x`). Designed for **Jewish adults and teens** — simple, fast, no per-device config beyond importing a WireGuard profile. WhatsApp always stays open.

**Stack:** Ubuntu 24.04 ARM · WireGuard · CoreDNS ×4 (one per tier) · iptables + policy routing · CleanBrowsing as upstream fallback · FastAPI portal (Hebrew, RTL) · Caddy (TLS for `filter-vpn.duckdns.org`)

> **No heavy proxy.** Earlier Squid + ICAP image filtering was removed for speed and reliability. Filtering is now **pure DNS** — fast, no CA install, no MITM. CleanBrowsing enforces the rest.

---

## 1. How it works

```
Phone (WireGuard app, tunnel-all 0.0.0.0/0)
  └─UDP 51820─▶ OCI server, wg0 10.100.0.1/16
       ├─ 10.100.1.x (Tier 1) ─▶ NAT ─▶ CoreDNS:5351 ─▶ CleanBrowsing Adult (185.228.168.10) ─▶ internet
       ├─ 10.100.2.x (Tier 2) ─▶ NAT ─▶ CoreDNS:5352 ─▶ CleanBrowsing Adult (185.228.168.10) ─▶ internet
       ├─ 10.100.3.x (Tier 3) ─▶ NAT ─▶ CoreDNS:5353 ─▶ CleanBrowsing Family (185.228.168.168) ─▶ internet
       └─ 10.100.4.x (Tier 4) ─▶ NAT ─▶ CoreDNS:5354 ─▶ CleanBrowsing Family (185.228.168.168) ─▶ internet
```

- Server maps `10.100.<tier>.x` → PBR tables `101-104` + `iptables DNAT` (UDP+TCP `53` → `127.0.0.1:5351-5354`) in `routing/pbr.sh:1`. No `REDIRECT` to proxy — all tiers direct NAT via `MASQUERADE`.
- Adding a user = allocating next IP in tier pool + one `[Peer]` in `wg0.conf` — filtering follows automatically.
- Blocked domains resolve to `10.100.0.1` → Hebrew RTL block page (`blockpage/server.py:1`, fronted by Caddy on `http://10.100.0.1` → `127.0.0.1:8081`) instead of timeout. WhatsApp (`whatsapp.com/net`) is never blocked.

DNS flow per tier: **our blocklists first** → if not blocked, forward to CleanBrowsing (`adult-filter-dns.cleanbrowsing.org` for Tier 1-2, `family-filter-dns.cleanbrowsing.org` for Tier 3-4). This gives two layers: local Hebrew block page + upstream Family/Adult enforcement.

---

## 2. Filtering tiers — precise spec (subnet architecture) — for Jewish adults & teens

| Tier | Pool | DNS | Upstream after our checks | Behavior — exact spec |
|------|------|-----|---------------------------|-----------------------|
| **1 Basic — בסיסי** | `10.100.1.0/24` (→`/20` ≈4000) | `:5351` | `adult-filter-dns.cleanbrowsing.org` `185.228.168.10` / `185.228.169.11` | **Blocks only pornography, adult content, phishing, and malware.** Everything else is open. |
| **2 Filtered — מסונן** | `10.100.2.0/24` | `:5352` | `adult-filter-dns.cleanbrowsing.org` `185.228.168.10` / `185.228.169.11` | **Basic blocks + Enforced YouTube Restricted Mode.** `www.youtube.com` → `restrict.youtube.com` etc. |
| **3 Mehadrin — מהדרין** | `10.100.3.0/24` | `:5353` | `family-filter-dns.cleanbrowsing.org` `185.228.168.168` / `185.228.169.168` | **Filtered blocks + Blocking mixed-content and open platforms (Reddit, X, Imgur, etc.).** `block-social.conf` (Reddit, X/Twitter, Imgur, Tumblr, 4chan/8chan, LiveJournal) + Family upstream. |
| **4 Mehadrin Min HaMehadrin — מהדרין מן המהדרין** | `10.100.4.0/24` | `:5354` | `family-filter-dns.cleanbrowsing.org` `185.228.168.168` / `185.228.169.168` | **Strict social media blocking + YouTube Restricted Mode + Basic blocks.** `block-social-strict.conf` (Facebook, Instagram, TikTok, Snapchat, Reddit, X, Tumblr, Imgur, Discord, Twitch, Pinterest, VK, etc. — **except** YouTube, LinkedIn, WhatsApp) — comprehensive. |

- Server: `10.100.0.1/16` on `wg0`. Each `/24` holds 240 clients (`.10–.250`), expandable to `/20` without renumbering.
- **WhatsApp** (`whatsapp.com`, `whatsapp.net`) is whitelisted on all tiers — never blocked locally nor via upstream.
- **LinkedIn + YouTube** stay open on Tier 4 Full (YouTube only in Restricted Mode). Tier 3/4 upstream Family Filter would otherwise block some, but our `safesearch.conf` + YouTube CNAME ensures restricted, not blocked.
- **CleanBrowsing Family Filter** (Tier 3-4) additionally blocks: adult, proxy/VPN bypass, mixed-content sites (Reddit, X, Tumblr, Imgur, 4chan/8chan), and enforces SafeSearch for Google/Bing/YouTube; malicious/phishing blocked. Tier 1-2 use Adult Filter (lighter, only adult/malware, no mixed-content).

> **DNS method for YouTube:** CNAME to `restrict.youtube.com` (Google-supported, never hard-coded IP). All tiers also CNAME Google/Bing to `forcesafesearch.google.com` via `safesearch.conf`. Realistic capacity on free shape (2 OCPUs / 12 GB) is **~500–600 concurrent tunnels**; scale with more instances.

---

## 3. Repo layout

| Path | Contents |
|------|----------|
| `docs/SPEC.md` | **Spec Sheet** — clean English spec for deployment/audit |
| `docs/deploy-ssh.md` | Deploy walkthrough over SSH (Windows `scp` → server `B→G`) |
| `deploy/oci-terraform/main.tf` | VCN, A1.Flex 2OCPU/12GB, security list (51820/udp, 443, 80, 22) |
| `deploy/cloud-init.yaml` | Packages + `ip_forward` |
| `deploy/Caddyfile` | Caddy reverse proxy: `filter-vpn.duckdns.org` → portal `:8000`, `http://10.100.0.1` → block page `:8081` |
| `wireguard/` | `wg0.conf.template` (`MTU 1380`), `gen-client.py` (IPAM `ipam.db`, `.conf`+QR), `change-tier.py` (non-permanent tier move), `add-peer.sh`, `revoke-peer.sh` |
| `coredns/` | `Corefile.5351`–`5354` (one per tier, forwarding to CleanBrowsing), `install-coredns.sh`, `gen-block-conf.py`, `blocklists/` (`domains-porn.txt`, `domains-malware.txt`, `domains-social.txt` for Tier3, `domains-social-strict.txt` for Tier4) + generated `block-*.conf` |
| `blockpage/` | Hebrew RTL block page (`server.py`, `block.html`, `filtervpn-blockpage.service` on `127.0.0.1:8081` fronted by Caddy) |
| `routing/` | `pbr.sh` (PBR 101-104, NAT, anti-spoof, inter-tier isolation, DNS DNAT UDP+TCP, DoH/DoT blocks — **no proxy REDIRECT**) |
| `proxy/` | *Legacy* — `squid.conf` (disabled, kept for reference), `ca/gen-ca.sh`, `worker/icap_worker.py` (fixed OPTIONS handler, now disabled by default) |
| `portal/` | Hebrew RTL portal for Jewish teens/adults (`app.py`: open enroll + `/change` tier move + `/ca.crt` + QR, no admin code) |
| `tests/` | `test-dns-tiers.sh`, `test-youtube-restrict.sh`, `test-wireguard-load.sh` |

---

## 4. Deploy

**Full guide → [`docs/deploy-ssh.md`](docs/deploy-ssh.md)**

Cheat sheet (on server, from `~/filtervpn`):

```bash
sudo apt-get install -y wireguard wireguard-tools iptables-persistent python3 qrencode curl dnsutils iproute2
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-filtervpn.conf && sudo sysctl --system

# WireGuard server (MTU 1380)
umask 077; wg genkey | sudo tee /etc/wireguard/server.key >/dev/null
sudo cat /etc/wireguard/server.key | wg pubkey | sudo tee /etc/wireguard/server.pub
sudo cp wireguard/wg0.conf.template /etc/wireguard/wg0.conf
sudo sed -i "s|__SERVER_PRIVATE_KEY__|$(sudo cat /etc/wireguard/server.key)|" /etc/wireguard/wg0.conf
sudo mkdir -p /opt/filtervpn/routing && sudo cp routing/pbr.sh /opt/filtervpn/routing/ && sudo chmod +x /opt/filtervpn/routing/pbr.sh
sudo systemctl enable --now wg-quick@wg0

# Routing + DNS (no proxy)
sudo bash routing/pbr.sh up && sudo netfilter-persistent save
sudo bash coredns/install-coredns.sh   # installs 4 CoreDNS units, generates block-*.conf → forwards to CleanBrowsing
sudo bash coredns/gen-block-conf.py    # regenerate after editing blocklists

# Block page + portal (Caddy TLS for filter-vpn.duckdns.org)
sudo mkdir -p /opt/filtervpn/blockpage && sudo cp blockpage/server.py blockpage/block.html /opt/filtervpn/blockpage/
sudo cp blockpage/filtervpn-blockpage.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now filtervpn-blockpage
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl enable --now caddy
ENDPOINT=filter-vpn.duckdns.org:51820 /home/ubuntu/.local/bin/uvicorn portal.app:app --host 127.0.0.1 --port 8000  # via systemd unit
```

---

## 5. Onboard / manage users (open, no username, no admin code)

**Portal (for Jewish teens and adults — recommended):** `https://filter-vpn.duckdns.org/` → pick tier (**Basic / מסונן / מהדרין / מהדרין מן המהדרין**) → `צור קובץ` → download `.conf` + QR. No name to type — system generates `vpn-xxxx` automatically. No CA install (proxy removed). Change tier anytime via `https://filter-vpn.duckdns.org/change` (just pick new tier, get new file).

**CLI (admin, still uses name for IPAM):**
```bash
# New user — allocates next IP in tier pool, writes .conf + QR
python3 wireguard/gen-client.py --tier 2 --name teen01 --endpoint "filter-vpn.duckdns.org:51820"
# Tier is not permanent — move user:
python3 wireguard/change-tier.py --name teen01 --tier 4 --apply
```

- Portal is username-free; CLI keeps `name` for tracking. Send portal link — user picks tier, downloads, imports in WireGuard app (<1 min).
- WhatsApp (`whatsapp.com/net`) whitelisted on all tiers — never blocked. YouTube + LinkedIn stay open on Tier 4 Full (YouTube only Restricted).

---

## 6. Verify & operate

```bash
bash tests/test-dns-tiers.sh          # porn → 10.100.0.1 on all tiers; Reddit/X/Imgur → 10.100.0.1 on 3+4 only
bash tests/test-youtube-restrict.sh   # www.youtube.com → restrict.youtube.com on 2/3/4
bash tests/test-wireguard-load.sh
sudo wg show wg0 latest-handshakes
dig @127.0.0.1 -p 5351 www.google.com +short   # 216.239.38.120 via SafeSearch (if enabled)
dig @127.0.0.1 -p 5354 reddit.com +short       # 10.100.0.1 (Tier4)
```

After `git pull` on server: `sudo cp coredns/Corefile.* /opt/filtervpn/coredns/ && python3 /opt/filtervpn/coredns/gen-block-conf.py && sudo systemctl restart coredns@5351 coredns@5352 coredns@5353 coredns@5354 && sudo bash routing/pbr.sh up`.

---

## 7. Limits & gotchas

- **Always-Free = 2 OCPUs / 12 GB** (not 4/24).
- `Out of capacity` on Ampere launch is common: retry AD/region or pilot E2.1.Micro.
- Idle free instances can be reclaimed: keep traffic alive, snapshot boot volume.
- DNS is now two-layer: our blocklists (→ `10.100.0.1` Hebrew page) **then** CleanBrowsing (Adult for 1-2, Family for 3-4) for the rest. If CleanBrowsing is unreachable, fallback fails open to upstream — monitor `coredns` logs.
- Lock down SSH (port 22) to your IP. Open enrollment means anyone with link can create a peer — rate-limit via Caddy or add Cloudflare in front if abused.

