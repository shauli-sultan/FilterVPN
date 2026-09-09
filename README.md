# WayGuard — DNS-over-TLS Filtering for the Jewish Community (OCI Always-Free)

Pure **DNS-over-TLS (DoT) filtering** on a single public IP (`84.13.84.211`) with **SNI-based tier routing** on port `853`. No VPN, no client tunnel — set your device's Private DNS to one of four hostnames and all queries are filtered at the DNS layer. Designed for **Jewish adults and teens** — simple, fast, no app needed. WhatsApp always stays open.

**Stack:** Ubuntu 24.04 ARM · CoreDNS ×4 (one per tier) · Nginx Stream `ssl_preread` SNI router on `:853` · CleanBrowsing as upstream fallback · FastAPI portal (Hebrew, RTL, no usernames) · Caddy (TLS for `filter-vpn.duckdns.org` + `yishiva-*.duckdns.org` certs)

> **No WireGuard, no proxy.** Previous Squid + ICAP + WireGuard stack was fully removed for speed and simplicity. Filtering is now **pure DoT** — set it once in Android/iOS/Windows and forget.

---

## 1. How it works

```
Device Private DNS → yishiva-*.duckdns.org:853 (DoT, TLS + SNI)
  └─ Nginx Stream (ssl_preread on :853) ──SNI──▶
       ├─ yishiva-basic.duckdns.org      ─▶ CoreDNS:5351 ─▶ CleanBrowsing Adult (185.228.168.10) ─▶ internet
       ├─ yishiva-filtered.duckdns.org   ─▶ CoreDNS:5352 ─▶ CleanBrowsing Adult (185.228.168.10) ─▶ internet
       ├─ yishiva-mehadrin.duckdns.org   ─▶ CoreDNS:5353 ─▶ CleanBrowsing Family (185.228.168.168) ─▶ internet
       └─ yishiva-super.duckdns.org      ─▶ CoreDNS:5354 ─▶ CleanBrowsing Family (185.228.168.168) ─▶ internet
Blocked → 0.0.0.0 or NXDOMAIN (or 10.100.0.1 Hebrew block page if queried via old VPN) — WhatsApp never blocked.
```

- **SNI routing:** `nginx` `stream { map $ssl_preread_server_name $backend }` on `0.0.0.0:853` forwards TLS ClientHello SNI to the correct local CoreDNS (`127.0.0.1:5351-5354` plain, or `8531-8534` with `tls` if passthrough). No PBR, no `wg0`.
- **Two-layer DNS:** **our blocklists first** → if not blocked, forward to CleanBrowsing (`adult-filter-dns` for Tier 1-2, `family-filter-dns` for Tier 3-4).
- Adding a user = nothing — just set Private DNS hostname. No IPAM, no `[Peer]`.

---

## 2. Filtering tiers — precise spec (same 4 tiers, DNS-only)

| Tier | Hostname (DoT) | CoreDNS | Upstream after our checks | Behavior — exact spec |
|------|---------------|---------|---------------------------|-----------------------|
| **1 Basic — בסיסי** | `yishiva-basic.duckdns.org` | `:5351` → `:8531` | `adult-filter-dns.cleanbrowsing.org` `185.228.168.10` / `.169.11` | **Blocks only pornography, adult content, phishing, and malware.** Everything else is open. |
| **2 Filtered — מסונן** | `yishiva-filtered.duckdns.org` | `:5352` → `:8532` | `adult-filter-dns` `185.228.168.10` | **Basic + Enforced YouTube Restricted Mode.** `www.youtube.com` → `restrict.youtube.com` |
| **3 Mehadrin — מהדרין** | `yishiva-mehadrin.duckdns.org` | `:5353` → `:8533` | `family-filter-dns.cleanbrowsing.org` `185.228.168.168` / `.169.168` | **Filtered + Blocking mixed-content and open platforms (Reddit, X, Imgur, etc.).** `block-social.conf` |
| **4 Mehadrin Min HaMehadrin — מהדרין מן המהדרין** | `yishiva-super.duckdns.org` | `:5354` → `:8534` | `family-filter-dns` `185.228.168.168` | **Strict social media blocking + YouTube Restricted Mode + Basic blocks.** `block-social-strict.conf` (Facebook, Instagram, TikTok, Snapchat, Reddit, X, Tumblr, Imgur, Discord, Twitch, etc. — **except** YouTube, LinkedIn, WhatsApp) |

- **WhatsApp** (`whatsapp.com`, `whatsapp.net`) is whitelisted on all tiers — never blocked locally nor via upstream.
- **LinkedIn + YouTube** stay open on Tier 4 (YouTube only Restricted). Tier 3-4 Family upstream would otherwise block some, but our `safesearch.conf` + YouTube CNAME ensures restricted, not blocked.
- **YouTube method:** CNAME to `restrict.youtube.com` (Google-supported, never hard-coded IP). All tiers also CNAME Google/Bing to `forcesafesearch.google.com` via `safesearch.conf` (Tier 2-4) or rely on Family upstream.

---

## 3. Repo layout (WayGuard)

| Path | Contents |
|------|----------|
| `docs/SPEC.md` | **Spec Sheet** — clean English spec (WayGuard) |
| `docs/deploy-ssh.md` | Deploy walkthrough (now DoT) |
| `deploy/oci-terraform/main.tf` | VCN, A1.Flex 2OCPU/12GB, security list (853/tcp DoT, 443, 80, 22) — **51820 removed** |
| `deploy/nginx-dot.conf` | **New** — Nginx stream SNI router for `:853` → `5351-5354` (or `8531-8534` TLS) |
| `coredns/` | `Corefile.5351`–`5354` (plain) + `Corefile.8531`–`8534` (DoT `tls` if passthrough), `gen-block-conf.py`, `blocklists/` |
| `blockpage/` | Hebrew block page (now only for legacy `10.100.0.1` — DoT returns `0.0.0.0`/`NXDOMAIN` instead) |
| `portal/` | Hebrew portal — no usernames, premade 4 tiers: explanation + per-tier download (was WireGuard, now DoT hostname copy) + QR + A4 print (`/print`) — tailored for Jewish teens/adults |
| `tests/` | `test-dns-tiers.sh` (now `kdig +tls` per hostname), `test-youtube-restrict.sh` |

*WireGuard stack (`wireguard/`, `routing/pbr.sh`, `proxy/`) removed — kept in git history for reference.*

---

## 4. Deploy DoT

```bash
# 1. Point 4 DuckDNS hostnames to 84.13.84.211 and obtain certs (SAN or 4 separate)
sudo apt-get install -y nginx certbot python3-certbot-nginx
# Use acme.sh with DuckDNS DNS-01 (recommended for 4 hosts on one IP)
curl https://get.acme.sh | sh
export DuckDNS_Token="YOUR_TOKEN"
~/.acme.sh/acme.sh --issue --dns dns_duckdns -d yishiva-basic.duckdns.org -d yishiva-filtered.duckdns.org -d yishiva-mehadrin.duckdns.org -d yishiva-super.duckdns.org
sudo mkdir -p /etc/nginx/tls && sudo cp ~/.acme.sh/yishiva-basic.duckdns.org_ecc/fullchain.cer /etc/nginx/tls/combined.pem

# 2. CoreDNS already runs on 5351-5354; add DoT listeners if passthrough (optional)
sudo cp coredns/Corefile.5351 /opt/filtervpn/coredns/Corefile.5351 && sudo systemctl restart coredns@5351 # etc.

# 3. Nginx SNI router
sudo cp deploy/nginx-dot.conf /etc/nginx/stream.d/dot.conf
sudo nginx -t && sudo systemctl reload nginx
sudo iptables -I INPUT 4 -p tcp --dport 853 -j ACCEPT && sudo netfilter-persistent save
# OCI VCN: open 853/tcp 0.0.0.0/0

# 4. Portal
ENDPOINT=yishiva-basic.duckdns.org uvicorn portal.app:app --host 127.0.0.1 --port 8000
```

---

## 5. Onboard users (no username, no POV)

**Portal:** `https://filter-vpn.duckdns.org/` → pick tier (**Basic / מסונן / מהדרין / מהדרין מן המהדרין**) → copy hostname `yishiva-*.duckdns.org` → paste into device Private DNS (DoT) → done. No file download needed (unlike WireGuard). QR on portal encodes the hostname for quick scan.

**Per-device setup (approved):**
- **Android 9+:** Settings → Network & Internet → Private DNS → `yishiva-mehadrin.duckdns.org` (or `basic/filtered/super` per tier) → Save
- **iOS 14+ / macOS:** Install `.mobileconfig` via `https://filter-vpn.duckdns.org/dot-profile?host=yishiva-mehadrin.duckdns.org` (or manual DNS → `yishiva-*.duckdns.org:853`)
- **Windows 11:** Settings → Network → DNS → `yishiva-*.duckdns.org`, DNS over TLS On
- **Print:** `https://filter-vpn.duckdns.org/print` → A4 landscape with 4 QRs (one per tier) for distribution — each QR is the DoT hostname.

---

## 6. Verify

```bash
kdig -d @84.13.84.211 +tls-ca +tls-host=yishiva-basic.duckdns.org pornhub.com   # → 0.0.0.0 / 10.100.0.1 (blocked)
kdig -d @84.13.84.211 +tls-ca +tls-host=yishiva-basic.duckdns.org reddit.com    # → 151.101.x.x (open, Tier1)
kdig -d @84.13.84.211 +tls-ca +tls-host=yishiva-mehadrin.duckdns.org reddit.com # → 0.0.0.0 (blocked, Tier3)
kdig -d @84.13.84.211 +tls-ca +tls-host=yishiva-super.duckdns.org tiktok.com    # → 0.0.0.0 (blocked, Tier4)
kdig -d @84.13.84.211 +tls-ca +tls-host=yishiva-super.duckdns.org whatsapp.com  # → 157.240.x.x (open, never blocked)
openssl s_client -connect 84.13.84.211:853 -servername yishiva-filtered.duckdns.org </dev/null 2>&1 | grep "Certificate"
```

---

## 7. Limits

- **Always-Free = 2 OCPUs / 12 GB** — DoT is far lighter than WireGuard+proxy, easily handles 500+ clients.
- No VPN overhead, no MTU/BBR tuning needed.
- If DoT blocked on restrictive network (port 853 filtered), fallback to DoH `https://yishiva-*.duckdns.org/dns-query` can be added via Nginx `https` reverse proxy.

