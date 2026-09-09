#!/usr/bin/env python3
"""Generate WireGuard client configs with tier-based IPAM.
Usage:
  python3 gen-client.py --tier 3 --name student001 --endpoint 1.2.3.4:51820 [--out clients/]
Allocates next free IP in 10.100.<tier>.10-250, appends [Peer] to wg0.conf,
writes <name>.conf + <name>.png (QR, if qrencode present).
"""
import argparse, ipaddress, os, sqlite3, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("FILTERVPN_IPAM_DB", os.path.join(BASE, "ipam.db"))
WG_CONF = os.environ.get("FILTERVPN_WG_CONF", "/etc/wireguard/wg0.conf")

TIERS = {1: "10.100.1.0/24", 2: "10.100.2.0/24", 3: "10.100.3.0/24", 4: "10.100.4.0/24"}
DNS_IP = "10.100.0.1"

def wg_genkey():
    priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    pub = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True, check=True).stdout.strip()
    return priv, pub

def init_db(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS leases (ip TEXT PRIMARY KEY, tier INT, name TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS server (k TEXT PRIMARY KEY, v TEXT)")

def next_ip(conn, tier):
    net = ipaddress.ip_network(TIERS[tier])
    used = {r[0] for r in conn.execute("SELECT ip FROM leases")}
    for i in range(10, 251):
        cand = str(net.network_address + i)
        if cand not in used:
            return cand
    raise SystemExit(f"No free IPs left in tier {tier} pool {TIERS[tier]} (expand to /20)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, required=True, choices=[1, 2, 3, 4])
    ap.add_argument("--name", required=True)
    ap.add_argument("--endpoint", required=True, help="PUBLIC_IP:51820")
    ap.add_argument("--out", default=os.path.join(BASE, "clients"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    conn = sqlite3.connect(DB)
    init_db(conn)

    row = conn.execute("SELECT ip FROM leases WHERE name=?", (args.name,)).fetchone()
    if row:
        print(f"Name {args.name} already has {row[0]}", file=sys.stderr)
        sys.exit(2)
    ip = next_ip(conn, args.tier)

    cpriv, cpub = wg_genkey()
    # Server pubkey: try env, then wg show (with sudo), then /etc/wireguard/server.pub
    spub = os.environ.get("FILTERVPN_SERVER_PUBKEY", "")
    if not spub or spub == "__SERVER_PUBLIC_KEY__":
        # try wg show without sudo, then with sudo, then file
        for cmd in (["wg", "show", "wg0", "public-key"], ["sudo", "wg", "show", "wg0", "public-key"], ["sudo", "cat", "/etc/wireguard/server.pub"]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
                if out and len(out) >= 40 and " " not in out:
                    spub = out
                    break
            except Exception:
                continue
        if not spub or spub == "__SERVER_PUBLIC_KEY__":
            try:
                # fallback: read server.pub directly if readable
                with open("/etc/wireguard/server.pub", encoding="utf-8") as f:
                    cand = f.read().strip()
                    if cand:
                        spub = cand
            except Exception:
                pass
    if not spub:
        spub = "__SERVER_PUBLIC_KEY__"

    client_conf = f"""[Interface]
PrivateKey = {cpriv}
Address = {ip}/16
DNS = {DNS_IP}
MTU = 1420

[Peer]
PublicKey = {spub}
Endpoint = {args.endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
    cpath = os.path.join(args.out, f"{args.name}.conf")
    with open(cpath, "w") as f:
        f.write(client_conf)

    qpath = os.path.join(args.out, f"{args.name}.png")
    try:
        subprocess.run(["qrencode", "-o", qpath, "-r", cpath], check=True)
        print(f"QR: {qpath}")
    except FileNotFoundError:
        print("qrencode not found; skipped QR", file=sys.stderr)

    conn.execute("INSERT INTO leases (ip, tier, name) VALUES (?,?,?)", (ip, args.tier, args.name))
    conn.commit()

    peer_block = f"\n[Peer]\n# {args.name} tier={args.tier}\nPublicKey = {cpub}\nAllowedIPs = {ip}/32\n"
    print(f"Allocated {ip} (tier {args.tier}) -> {cpath}")
    print("Append to server wg0.conf (or run add-peer.sh):")
    print(peer_block)

if __name__ == "__main__":
    main()
