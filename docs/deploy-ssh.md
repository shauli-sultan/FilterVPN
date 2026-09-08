# Deploy FilterVPN over SSH (Ubuntu 24.04 ARM on OCI)

You already have the Oracle server running Ubuntu 24.04 ARM with a public IP.
Everything below runs **over SSH** — Part A from your Windows PC, Part B
pasted into the SSH session on the server.

Assumptions: server user `ubuntu`, you have the private key, and the OCI
security list allows UDP 51820 (WireGuard), TCP 443 (portal, optional),
and TCP 22 (your SSH). Repo lives at `C:\Users\user\Documents\FilterVPN`.

---

## Part A — From your Windows PC

### A1. Connect

```powershell
ssh -i "$env:USERPROFILE\.ssh\filtervpn" ubuntu@<PUBLIC_IP>
```

Keep this window open — Parts B–D run inside it.

### A2. Copy the repo to the server

Open a **second** PowerShell window (same PC) and run:

```powershell
scp -i "$env:USERPROFILE\.ssh\filtervpn" -r C:\Users\user\Documents\FilterVPN ubuntu@<PUBLIC_IP>:/home/ubuntu/filtervpn
```

Verify inside the SSH session:

```bash
ls ~/filtervpn
# expect: coredns/ deploy/ docs/ portal/ proxy/ routing/ tests/ wireguard/
```

---

## Part B — Base setup (SSH session, on the server)

```bash
sudo apt-get update
sudo apt-get install -y wireguard wireguard-tools iptables-persistent \
  squid-openssl python3 python3-pip qrencode curl dnsutils iproute2

echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-filtervpn.conf
sudo sysctl --system
sysctl net.ipv4.ip_forward   # must print 1
```

---

## Part C — WireGuard + routing + firewall (SSH session)

```bash
# 1. Server keys
umask 077
wg genkey | sudo tee /etc/wireguard/server.key >/dev/null
sudo cat /etc/wireguard/server.key | wg pubkey | sudo tee /etc/wireguard/server.pub
sudo chmod 600 /etc/wireguard/server.key

# 2. Server config from template
sudo cp ~/filtervpn/wireguard/wg0.conf.template /etc/wireguard/wg0.conf
sudo sed -i "s|__SERVER_PRIVATE_KEY__|$(sudo cat /etc/wireguard/server.key)|" /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf

# 3. Routing script in place, interface up
sudo mkdir -p /opt/filtervpn/routing
sudo cp ~/filtervpn/routing/pbr.sh /opt/filtervpn/routing/pbr.sh
sudo chmod +x /opt/filtervpn/routing/pbr.sh
sudo systemctl enable --now wg-quick@wg0
sudo wg show   # interface wg0 on 10.100.0.1/16, no peers yet

# 4. Policy routing + NAT + per-tier DNS redirects + Tier 2/3 proxy redirects
sudo bash ~/filtervpn/routing/pbr.sh up
sudo netfilter-persistent save
ip rule list   # expect: from 10.100.1/2/3/4.0/24 lookup 101/102/103/104
```

---

## Part D — CoreDNS tier instances (SSH session)

```bash
sudo bash ~/filtervpn/coredns/install-coredns.sh
sudo bash ~/filtervpn/coredns/update-blocklists.sh   # optional refresh
sudo systemctl restart coredns@5351 coredns@5352 coredns@5353 coredns@5354
sudo systemctl is-active coredns@5351 coredns@5352 coredns@5353 coredns@5354
```

What you get: Tier 1→5351, Tier 2→5352 (malware/adult block),
Tier 3→5353 (+ YouTube CNAME to `restrict.youtube.com`),
Tier 4→5354 (+ social sink to 0.0.0.0).

---

## Part E — Squid proxy + Root CA, Tier 2/3 (SSH session)

```bash
sudo bash ~/filtervpn/proxy/ca/gen-ca.sh
sudo cp ~/filtervpn/proxy/squid.conf /etc/squid/squid.conf
sudo cp ~/filtervpn/proxy/ca/squid-dynamic.pem /opt/filtervpn/proxy/ca/squid-dynamic.pem
sudo systemctl restart squid
sudo systemctl enable squid

# ICAP content worker: image inspection (NudeNet model if installed, else heuristic)
nohup python3 ~/filtervpn/proxy/worker/icap_worker.py >/var/log/icap-worker.log 2>&1 &
sleep 1; cat /var/log/icap-worker.log
# Optional: real nudity detection (open-source NudeNet, onnxruntime CPU, one-time ~100-300MB download)
pip install -r ~/filtervpn/proxy/worker/requirements-ml.txt
# then restart the worker; blocked images are replaced with a Hebrew "image blocked" SVG
curl -x http://127.0.0.1:3128 -I http://example.com | head -3
```

Now download the CA to your PC (second PowerShell window):

```powershell
scp -i "$env:USERPROFILE\.ssh\filtervpn" ubuntu@<PUBLIC_IP>:/home/ubuntu/filtervpn/proxy/ca/FilterVPN-RootCA.crt "$env:USERPROFILE\Desktop\"
```

Every Tier 2/3 phone installs `FilterVPN-RootCA.crt` **once**:
Android → Settings → Security → Install certificate;
iPhone → AirDrop/mail it → Settings → General → About →
Certificate Trust Settings → enable full trust.

> Squid only intercepts Tier 2/3 (`pbr.sh` REDIRECTs). Tier 1/4 go direct.
> YouTube/social/banking are spliced, never MITM'd (certificate pinning) —
> those are enforced at DNS level instead.

### Block page server (Hebrew explanation instead of connection failure)

Blocked domains resolve to `10.100.0.1` — this serves the Hebrew "site
blocked + why" page on port 80 there:

```bash
sudo mkdir -p /opt/filtervpn/blockpage
sudo cp ~/filtervpn/blockpage/server.py ~/filtervpn/blockpage/block.html /opt/filtervpn/blockpage/
sudo cp ~/filtervpn/blockpage/filtervpn-blockpage.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now filtervpn-blockpage
curl -H "Host: pornhub.com" http://10.100.0.1/ | head -5   # Hebrew 403 page
```

Optional Hebrew Squid error page (for Squid-generated HTTPS errors on Tier 2/3):

```bash
sudo cp /usr/share/squid/errors/ERR_ACCESS_DENIED /root/ERR_ACCESS_DENIED.bak
sudo cp ~/filtervpn/proxy/hebrew-errors/ERR_FILTERVPN /usr/share/squid/errors/ERR_ACCESS_DENIED
sudo systemctl reload squid
```

---

## Part F — First user, end to end (SSH session)

```bash
export FILTERVPN_SERVER_PUBKEY="$(sudo cat /etc/wireguard/server.pub)"
python3 ~/filtervpn/wireguard/gen-client.py \
  --tier 3 --name student001 --endpoint "<PUBLIC_IP>:51820"
# prints e.g. 10.100.3.10 and writes:
#   wireguard/clients/student001.conf  +  wireguard/clients/student001.png (QR)
```

Hot-add the peer (use the pubkey the script printed):

```bash
sudo bash ~/filtervpn/wireguard/add-peer.sh "<CLIENT_PUBKEY>" "10.100.3.10/32" student001 3
sudo wg show wg0
```

Fetch the config to your PC (second PowerShell window):

```powershell
scp -i "$env:USERPROFILE\.ssh\filtervpn" ubuntu@<PUBLIC_IP>:/home/ubuntu/filtervpn/wireguard/clients/student001.conf "$env:USERPROFILE\Desktop\"
scp -i "$env:USERPROFILE\.ssh\filtervpn" ubuntu@<PUBLIC_IP>:/home/ubuntu/filtervpn/wireguard/clients/student001.png "$env:USERPROFILE\Desktop\"
```

Import `student001.conf` (or scan the QR) in the WireGuard phone app,
turn the tunnel on, and browse. On the server, watch live traffic:

```bash
sudo wg show wg0 latest-handshakes
sudo tail -f /var/log/squid/access.log   # Tier 2/3 web traffic
```

Revoke a user anytime:

```bash
sudo bash ~/filtervpn/wireguard/revoke-peer.sh "<CLIENT_PUBKEY>"
```

---

## Part G — Verify filtering (SSH session)

```bash
bash ~/filtervpn/tests/test-dns-tiers.sh
bash ~/filtervpn/tests/test-youtube-restrict.sh
bash ~/filtervpn/tests/test-wireguard-load.sh
```

Expected: `www.youtube.com` resolves normally on 5351/5352 but CNAMEs to
`restrict.youtube.com` on 5353/5354; `www.google.com` / `www.google.co.il`
CNAME to `forcesafesearch.google.com` on ALL tiers (SafeSearch locked on); `tiktok.com` and all porn/hentai domains
resolve to `10.100.0.1` — open `http://<any-blocked-site>/` in a browser to see
the Hebrew block explanation. (HTTPS to blocked domains can't show the page
without MITM — browser shows a connection error instead; Tier 2/3 HTTPS gets
the Hebrew Squid/ICAP block page.)

---

## Troubleshooting (all on the server over SSH)

| Symptom | Check / fix |
|---|---|
| Handshake never completes | `sudo wg show`; `sudo journalctl -u wg-quick@wg0`; OCI security list UDP 51820 open; client Endpoint = `<PUBLIC_IP>:51820` |
| Connected, no internet | `sysctl net.ipv4.ip_forward` (=1); re-run `sudo bash ~/filtervpn/routing/pbr.sh up`; `sudo iptables -t nat -L POSTROUTING -v` shows MASQUERADE |
| DNS bypass / wrong tier | `ip rule list` shows 4 rules; `sudo iptables -t nat -L PREROUTING -v` shows DNAT to 5351–5354; phone must use tunnel DNS only |
| YouTube not restricted | Confirm client IP is `10.100.3.x`/`10.100.4.x`; toggle phone airplane mode (DNS cache); re-run `test-youtube-restrict.sh` |
| HTTPS errors on Tier 2/3 | Root CA missing on phone — install + trust `FilterVPN-RootCA.crt` |
| Squid errors | `sudo systemctl status squid`; `sudo tail -50 /var/log/squid/cache.log`; confirm `/opt/filtervpn/proxy/ca/squid-dynamic.pem` exists |

## Updating after a `git pull`

```bash
cd ~/filtervpn && git pull
sudo cp ~/filtervpn/coredns/Corefile.* ~/filtervpn/coredns/gen-block-conf.py ~/filtervpn/coredns/safesearch.conf /opt/filtervpn/coredns/
sudo cp ~/filtervpn/coredns/blocklists/domains-*.txt ~/filtervpn/coredns/blocklists/block-*.conf /opt/filtervpn/coredns/blocklists/
sudo systemctl restart coredns@5351 coredns@5352 coredns@5353 coredns@5354
sudo cp ~/filtervpn/proxy/squid.conf /etc/squid/squid.conf && sudo systemctl reload squid
sudo bash ~/filtervpn/routing/pbr.sh up
```
