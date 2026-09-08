#!/usr/bin/env python3
"""Change a user's filtering tier (not permanent).

Moves an existing client to a new tier's IP pool, updates IPAM, wg0.conf
and the live WireGuard interface, and re-generates the client's .conf + QR.

Usage:
  python3 change-tier.py --name student001 --tier 2 [--endpoint filter-vpn.duckdns.org:51820] [--keep-keys]
  python3 change-tier.py --name student001 --tier 4 --apply

If --apply is given, the script also hot-patches the live wg0 interface
(revoke old peer + add new peer). Otherwise it prints the new peer block
to append manually.

Keeps the portal's ADMIN_TOKEN gate enforced when called via portal/app.py.
Direct CLI use is admin-only.
"""
import argparse, ipaddress, os, re, sqlite3, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("FILTERVPN_IPAM_DB", os.path.join(BASE, "ipam.db"))
WG_CONF = os.environ.get("FILTERVPN_WG_CONF", "/etc/wireguard/wg0.conf")
CLIENTS = os.path.join(BASE, "clients")
TIERS = {1: "10.100.1.0/24", 2: "10.100.2.0/24", 3: "10.100.3.0/24", 4: "10.100.4.0/24"}
DNS_IP = "10.100.0.1"

def wg_genkey():
    priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    pub = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True, check=True).stdout.strip()
    return priv, pub

def pub_from_priv(priv):
    return subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True, check=True).stdout.strip()

def _read_wg_text(wg_path):
    try:
        return open(wg_path, encoding="utf-8", errors="ignore").read()
    except PermissionError:
        try:
            return subprocess.check_output(["sudo", "cat", wg_path], text=True)
        except Exception:
            return ""
    except FileNotFoundError:
        return ""

def find_peer_in_wgconf(name, wg_path):
    """Return (pubkey, allowed_ip) for a peer by name comment, or (None, None)."""
    text = _read_wg_text(wg_path)
    if not text:
        return None, None
    # Look for block: [Peer]\n# name tier=X\nPublicKey = ...\nAllowedIPs = ...
    # Fallback: search for "# <name>" nearby PublicKey
    pat = re.compile(r"\[Peer\][^\[]*?#\s*" + re.escape(name) + r"\b[^\[]*?PublicKey\s*=\s*(\S+)[^\[]*?AllowedIPs\s*=\s*(\S+)", re.S)
    m = pat.search(text)
    if m:
        return m.group(1), m.group(2)
    # fallback: any PublicKey near name
    if f"# {name}" in text:
        idx = text.index(f"# {name}")
        snippet = text[max(0, idx-200): idx+500]
        pm = re.search(r"PublicKey\s*=\s*(\S+)", snippet)
        im = re.search(r"AllowedIPs\s*=\s*(\S+)", snippet)
        if pm:
            return pm.group(1), (im.group(1) if im else None)
    return None, None

def next_ip(conn, tier, exclude=None):
    net = ipaddress.ip_network(TIERS[tier])
    used = {r[0] for r in conn.execute("SELECT ip FROM leases")}
    if exclude and exclude in used:
        used.remove(exclude)  # freeing old IP makes it available for reuse if same tier
    for i in range(10, 251):
        cand = str(net.network_address + i)
        if cand not in used:
            return cand
    raise SystemExit(f"No free IPs left in tier {tier} pool {TIERS[tier]} (expand to /20)")

def remove_peer_from_conf(wg_path, pub):
    if not pub:
        return
    text = _read_wg_text(wg_path)
    if not text:
        return
    lines = text.splitlines(keepends=True)
    out, skip = [], False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("[Peer]"):
            block = "".join(lines[i:i+5])
            skip = pub in block
            if not skip:
                out.append(ln)
            continue
        if skip:
            if f"PublicKey = {pub}" in ln or ln.strip().startswith("AllowedIPs") or ln.strip().startswith("#"):
                continue
            skip = False
        out.append(ln)
    new_text = "".join(out)
    try:
        open(wg_path, "w", encoding="utf-8").write(new_text)
    except PermissionError:
        subprocess.run(["sudo", "tee", wg_path], input=new_text.encode(), check=False, capture_output=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="existing client name")
    ap.add_argument("--tier", type=int, required=True, choices=[1,2,3,4], help="new tier")
    ap.add_argument("--endpoint", default=os.environ.get("ENDPOINT", "filter-vpn.duckdns.org:51820"))
    ap.add_argument("--out", default=CLIENTS)
    ap.add_argument("--keep-keys", action="store_true", help="reuse existing private key (keep client's pubkey, only IP changes)")
    ap.add_argument("--apply", action="store_true", help="also hot-patch live wg0 (wg set remove+add)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS leases (ip TEXT PRIMARY KEY, tier INT, name TEXT)")
    row = conn.execute("SELECT ip, tier FROM leases WHERE name=?", (args.name,)).fetchone()
    if not row:
        print(f"No lease found for name {args.name} (did you enroll first?)", file=sys.stderr)
        sys.exit(2)
    old_ip, old_tier = row
    if old_tier == args.tier:
        print(f"{args.name} already on tier {args.tier} ({old_ip})", file=sys.stderr)
        sys.exit(0)

    old_pub, old_allowed = find_peer_in_wgconf(args.name, WG_CONF)
    # Try to reuse private key if requested
    old_priv = None
    if args.keep_keys:
        cpath_old = os.path.join(args.out, f"{args.name}.conf")
        if os.path.exists(cpath_old):
            try:
                txt = open(cpath_old, encoding="utf-8").read()
                m = re.search(r"PrivateKey\s*=\s*(\S+)", txt)
                if m:
                    old_priv = m.group(1)
            except Exception:
                pass
        if not old_priv:
            print("keep-keys requested but no existing .conf/private key found; generating new keys", file=sys.stderr)
            args.keep_keys = False

    # Allocate new IP (free old one first conceptually)
    new_ip = next_ip(conn, args.tier, exclude=old_ip)

    if args.keep_keys:
        cpriv = old_priv
        cpub = pub_from_priv(cpriv)
    else:
        cpriv, cpub = wg_genkey()

    # Server pubkey: try env, then wg show (with sudo), then server.pub file
    spub = os.environ.get("FILTERVPN_SERVER_PUBKEY", "")
    if not spub or spub == "__SERVER_PUBLIC_KEY__":
        for cmd in (["wg", "show", "wg0", "public-key"], ["sudo", "wg", "show", "wg0", "public-key"], ["sudo", "cat", "/etc/wireguard/server.pub"]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
                if out and len(out) >= 40 and " " not in out:
                    spub = out
                    break
            except Exception:
                continue
        if not spub:
            try:
                with open("/etc/wireguard/server.pub", encoding="utf-8") as f:
                    cand = f.read().strip()
                    if cand:
                        spub = cand
            except Exception:
                pass
    if not spub:
        spub = "__SERVER_PUBLIC_KEY__"

    # Update IPAM atomically: delete old, insert new
    conn.execute("DELETE FROM leases WHERE name=?", (args.name,))
    conn.execute("INSERT INTO leases (ip, tier, name) VALUES (?,?,?)", (new_ip, args.tier, args.name))
    conn.commit()

    # Remove old peer from wg0.conf (by old pubkey if known) and runtime
    if old_pub:
        remove_peer_from_conf(WG_CONF, old_pub)
        if args.apply:
            subprocess.run(["sudo", "wg", "set", "wg0", "peer", old_pub, "remove"], check=False)

    # Append new peer to wg0.conf and runtime
    peer_block = f"\n[Peer]\n# {args.name} tier={args.tier}\nPublicKey = {cpub}\nAllowedIPs = {new_ip}/32\n"
    try:
        with open(WG_CONF, "a", encoding="utf-8") as f:
            f.write(peer_block)
    except PermissionError:
        subprocess.run(["sudo", "tee", "-a", WG_CONF], input=peer_block.encode(), check=False, capture_output=True)
    if args.apply:
        subprocess.run(["sudo", "wg", "set", "wg0", "peer", cpub, "allowed-ips", f"{new_ip}/32"], check=False)

    # Write new client conf
    client_conf = f"""[Interface]
PrivateKey = {cpriv}
Address = {new_ip}/16
DNS = {DNS_IP}
MTU = 1380

[Peer]
PublicKey = {spub}
Endpoint = {args.endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
    cpath = os.path.join(args.out, f"{args.name}.conf")
    with open(cpath, "w", encoding="utf-8") as f:
        f.write(client_conf)
    qpath = os.path.join(args.out, f"{args.name}.png")
    try:
        subprocess.run(["qrencode", "-o", qpath, "-r", cpath], check=True)
        print(f"QR: {qpath}")
    except FileNotFoundError:
        print("qrencode not found; skipped QR", file=sys.stderr)

    print(f"Moved {args.name}: {old_ip} (tier {old_tier}) -> {new_ip} (tier {args.tier})")
    print(f"Wrote {cpath}")
    if not args.apply:
        print("Run with --apply to hot-patch live wg0, or manually:")
        print(peer_block)
        if old_pub:
            print(f"# removed old peer {old_pub} ({old_allowed})")

if __name__ == "__main__":
    main()
