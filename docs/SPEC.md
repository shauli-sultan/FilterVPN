# FilterVPN — English Spec Sheet (DNS-Only, OCI Always-Free)

**Version:** 2.0 (DNS-only, no proxy) — 2026-09-09  
**Audience:** Jewish adults and teens (yeshiva students, working adults, families) — simple Hebrew portal, no technical setup beyond WireGuard import. WhatsApp always whitelisted for family contact.  
**Hosting:** Single Oracle Cloud Always-Free Ampere A1 (VM.Standard.A1.Flex, 2 OCPUs / 12 GB, `il-jerusalem-1`, `filter-vpn.duckdns.org` → `84.13.84.211`), Ubuntu 24.04 ARM. Scales to ~500–600 concurrent WireGuard tunnels; add instances beyond.

---

## 1. Purpose

Provide **per-user, per-tier DNS filtering** over an encrypted WireGuard tunnel. One server, no per-device MDM. User picks a tier on the portal, gets a WireGuard profile (`*.conf` + QR), and all traffic is filtered at the DNS layer according to the IP pool they were assigned. Tier can be changed at any time (non-permanent) via portal or CLI.

**Why DNS-only:** Previous Squid `ssl_bump` + ICAP image filtering was removed for speed, reliability, and to avoid CA install. Heavy MITM broke cert-pinned apps and caused `500 ERR_ICAP_FAILURE` + `forwarding loop` under load. DNS filtering is fast, works without CA, and respects app pinning. CleanBrowsing provides the second layer.

---

## 2. Architecture

### 2.1 Network

```
Client (WireGuard app, tunnel-all 0.0.0.0/0, ::/0, keepalive 25)
  └─ UDP 51820 ─▶ OCI VM, wg0 10.100.0.1/16, MTU 1380
       ├─ 10.100.1.0/24 (Tier 1) ─▶ NAT (MASQUERADE enp0s6) ─▶ CoreDNS:5351 ─▶ CleanBrowsing Adult
       ├─ 10.100.2.0/24 (Tier 2) ─▶ NAT ─▶ CoreDNS:5352 ─▶ CleanBrowsing Adult
       ├─ 10.100.3.0/24 (Tier 3) ─▶ NAT ─▶ CoreDNS:5353 ─▶ CleanBrowsing Family
       └─ 10.100.4.0/24 (Tier 4) ─▶ NAT ─▶ CoreDNS:5354 ─▶ CleanBrowsing Family
Blocked DNS → 10.100.0.1:80 (Caddy) → 127.0.0.1:8081 Hebrew block page
```

- **PBR:** `routing/pbr.sh` creates tables `101-104` (`10.100.1-4.0/24 → table 10x`), `ip rule` `1001-1004`, `MASQUERADE` on `WAN` (`enp0s6` autodetected), `FORWARD` anti-spoof + inter-tier isolation (`10.100.x ↔ 10.100.y` DROP), `TCPMSS --clamp-mss-to-pmtu`.
- **DNS hijack:** `iptables -t nat PREROUTING -i wg0 -s 10.100.<tier>.0/24 -p udp,tcp --dport 53 -j DNAT --to 127.0.0.1:535<1-4>` — forces tier DNS, blocks client DoH/DoT (`FORWARD DROP` for `1.1.1.1/8.8.8.8:443` and `853/tcp`).
- **No proxy REDIRECT:** All tiers `direct NAT` — no `REDIRECT 3128/3129`, no `squid` in data path.
- **MTU:** `wireguard/wg0.conf.template:MTU 1380` + `ip link set wg0 mtu 1380` + MSS clamp.

### 2.2 DNS — Two Layers

**Layer 1 (local, → `10.100.0.1` Hebrew block page):**
- `coredns/blocklists/domains-porn.txt` (71+ apex, `block-porn.conf` regex `^(.*\.)?(pornhub|xvideos|...)\.$` → `A 10.100.0.1`) — **all tiers**
- `domains-malware.txt` (`block-malware.conf`) — **all tiers**
- `safesearch.conf` (`www.google.com → forcesafesearch.google.com`) — all tiers (Google/Bing SafeSearch)
- YouTube rewrites (Tier 2-4): `www.youtube.com`, `m.youtube.com`, `youtubei.googleapis.com`, `youtube.googleapis.com`, `www.youtube-nocookie.com` → `restrict.youtube.com` (Google-supported CNAME)
- `domains-social.txt` (mixed-content: `reddit`, `x.com`/`twitter`, `imgur`, `tumblr`, `4chan`, `8ch`, `livejournal`) → Tier 3 + Tier 4
- `domains-social-strict.txt` (comprehensive: above + `facebook`, `instagram`, `tiktok`, `snapchat`, `vk`, `discord`, `twitch`, `pinterest`, `threads`, `wechat`, `telegram` — **except** `youtube.com`, `linkedin.com`, `whatsapp.com/net`) → Tier 4 only

**Layer 2 (upstream fallback):**
- Tier 1-2 → `adult-filter-dns.cleanbrowsing.org` — `185.228.168.10` / `185.228.169.11` (blocks adult/porn, phishing/malware)
- Tier 3-4 → `family-filter-dns.cleanbrowsing.org` — `185.228.168.168` / `185.228.169.168` (Adult + **blocks proxy/VPN bypass, mixed-content like Reddit/X/Tumblr/Imgur, enforces SafeSearch for Google/Bing/YouTube, blocks malicious/phishing**)

If not blocked locally, query is forwarded to CleanBrowsing. WhatsApp (`whatsapp.com/net`) is never in any blocklist and is not blocked by CleanBrowsing.

**Block page:** `blockpage/server.py` on `127.0.0.1:8081` (systemd `filtervpn-blockpage`), fronted by Caddy `http://10.100.0.1 → 127.0.0.1:8081`. Categorises `porn`/`social`/`malware` with Hebrew `block.html`.

### 2.3 WireGuard

- Server `wg0.conf.template`: `10.100.0.1/16`, `ListenPort 51820`, `MTU 1380`, `Table off`, `PostUp pbr.sh up`. Each peer: `PublicKey`, `AllowedIPs = 10.100.<tier>.x/32`, comment `# name tier=X`.
- IPAM: `wireguard/ipam.db` (SQLite `leases(ip, tier, name)`), allocator `wireguard/gen-client.py` (`10.100.<tier>.10-250`, expandable to `/20` without renumbering). `change-tier.py` moves IP pools non-permanently (`--apply` hot-patches `wg set` + `wg0.conf`).
- Server pubkey fetched via `cat /etc/wireguard/server.pub` (`chmod 755 /etc/wireguard; chmod 644 server.pub`).

### 2.4 Portal & TLS

- `portal/app.py` (FastAPI, Hebrew RTL, open enrollment, no admin code) — `GET /` enroll, `POST /enroll`, `GET /change` + `POST /change` (tier move), `GET /ca.crt` (optional, now not required), `GET /files/{name}.conf/.png` (`application/octet-stream` + `download` + `nosniff` to avoid `.conf.txt` on Windows), `POST /api/enroll`/`/api/change-tier`.
- Tier UI non-technical, tailored for Jewish teens/adults: Tier 1 for working adults, Tier 2 for teens needing YouTube for learning, Tier 3 for yeshiva students avoiding mixed-content, Tier 4 for young teens needing maximal quiet.
- Caddy `deploy/Caddyfile`: `filter-vpn.duckdns.org → 127.0.0.1:8000` (auto TLS via Let's Encrypt), `http://10.100.0.1 → 127.0.0.1:8081` (block page). Ports `80/443` open in VCN + host `iptables`.

---

## 3. Filtering Tiers — Precise Definition (as implemented)

> **WhatsApp is whitelisted on all tiers.** YouTube and LinkedIn stay open on Tier 4 Full (YouTube only in Restricted Mode).

| Tier | Subnet (pool) | CoreDNS | Upstream | Precise Behavior — exact spec |
|------|---------------|---------|----------|--------------------------------|
| **1 Basic — בסיסי** | `10.100.1.0/24` | `:5351` | `adult-filter-dns.cleanbrowsing.org` `185.228.168.10` / `185.228.169.11` | **Blocks only pornography, adult content, phishing, and malware.** Everything else is open. |
| **2 Filtered — מסונן** | `10.100.2.0/24` | `:5352` | `adult-filter-dns.cleanbrowsing.org` `185.228.168.10` / `185.228.169.11` | **Basic blocks + Enforced YouTube Restricted Mode.** |
| **3 Mehadrin — מהדרין** | `10.100.3.0/24` | `:5353` | `family-filter-dns.cleanbrowsing.org` `185.228.168.168` / `185.228.169.168` | **Filtered blocks + Blocking mixed-content and open platforms (Reddit, X, Imgur, etc.).** |
| **4 Mehadrin Min HaMehadrin — מהדרין מן המהדרין** | `10.100.4.0/24` | `:5354` | `family-filter-dns.cleanbrowsing.org` `185.228.168.168` / `185.228.169.168` | **Strict social media blocking + YouTube Restricted Mode + Basic blocks.** |


Capacity: each `/24` = 240 clients (`.10–.250`), `/20` = ~4000 without renumbering. Server `10.100.0.1/16`.

---

## 4. Security & Limits

- **VCN Security List:** Ingress `51820/udp` (WireGuard), `80/tcp` (LE HTTP-01), `443/tcp` (portal), `22/tcp` (SSH, lock to your IP). Egress `all`. Host `iptables INPUT` mirrors (before `REJECT`).
- **Always-Free:** `2 OCPUs / 12 GB` (not `4/24` shape max). `Out of capacity` on Ampere is common — retry AD/region or `E2.1.Micro`.
- **Reclaim:** Idle free instances can be reclaimed — keep traffic alive, snapshot boot volume.
- **Open enrollment:** Portal has no admin code — anyone with link can create a peer. Rate-limit via Caddy/Cloudflare if abused. No `ADMIN_TOKEN` needed.
- **No MITM:** No CA install required (proxy removed). Old `proxy/ca/FilterVPN-RootCA.crt` remains at `/ca.crt` for legacy Tier2 devices but is optional.

---

## 5. Operations

```bash
# Add user (Tier 4 full)
python3 wireguard/gen-client.py --tier 4 --name teen01 --endpoint filter-vpn.duckdns.org:51820
sudo bash wireguard/add-peer.sh "<PUB>" "10.100.4.10/32" teen01 4

# Move tier (non-permanent)
python3 wireguard/change-tier.py --name teen01 --tier 2 --apply

# Verify
bash tests/test-dns-tiers.sh
bash tests/test-youtube-restrict.sh  # www.youtube.com → restrict.youtube.com on 2/3/4
dig @127.0.0.1 -p 5353 reddit.com +short  # → 10.100.0.1 (Tier3)
dig @127.0.0.1 -p 5351 reddit.com +short  # → via CleanBrowsing Adult (not blocked, Tier1)
sudo wg show wg0 latest-handshakes
```

After `git pull` on server: `sudo cp coredns/Corefile.* coredns/blocklists/* /opt/filtervpn/coredns/ && python3 /opt/filtervpn/coredns/gen-block-conf.py && sudo systemctl restart coredns@5351 coredns@5352 coredns@5353 coredns@5354 && sudo bash routing/pbr.sh up && sudo netfilter-persistent save && sudo cp portal/app.py /home/ubuntu/filtervpn/portal/app.py && sudo systemctl restart filtervpn-portal`.

