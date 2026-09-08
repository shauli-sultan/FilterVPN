#!/usr/bin/env python3
"""FilterVPN block-page server (Hebrew) — explains WHY a site is blocked.

Blocked domains resolve to the VPN server IP (see coredns/gen-block-conf.py
FILTERVPN_BLOCK_IP, default 10.100.0.1); this serves HTTP :80 there so users
see a Hebrew explanation instead of a bare connection failure.

Run:  BLOCK_HOST=10.100.0.1 BLOCK_PORT=80 python3 server.py
systemd: filtervpn-blockpage.service
"""
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BL = os.path.join(HERE, "..", "coredns", "blocklists")


def load(fname):
    out = set()
    try:
        with open(os.path.join(BL, fname), encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    out.add(line)
    except FileNotFoundError:
        pass
    return out


PORN = load("domains-porn.txt")
SOCIAL = load("domains-social.txt")
MALWARE = load("domains-malware.txt")

REASONS = {
    "hentai": "תוכן הנטאי / תוכן מיני מצויר — חסום בכל רמות הסינון",
    "adult": "אתר פורנו / תוכן למבוגרים — חסום בכל רמות הסינון",
    "social": "רשת חברתית — חסומה ברמת הסינון המקסימלית (רמה 4)",
    "malware": "אתר מסוכן (נוזקה או פישינג) — נחסם להגנתכם",
    "blocked": "האתר נמצא ברשימת החסימה של מערכת הסינון",
}


def base_match(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def categorize(host):
    h = host.split(":")[0].lower().rstrip(".")
    if "hentai" in h:
        return "hentai"
    if base_match(h, PORN):
        return "adult"
    if base_match(h, SOCIAL):
        return "social"
    if base_match(h, MALWARE):
        return "malware"
    return "blocked"


with open(os.path.join(HERE, "block.html"), encoding="utf-8") as f:
    TEMPLATE = f.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "FilterVPN-BlockPage"

    def do_GET(self):
        if self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        host = self.headers.get("Host", "")
        cat = categorize(host)
        page = (TEMPLATE
                .replace("{host}", html.escape(host) if host else "האתר המבוקש")
                .replace("{reason}", REASONS[cat]))
        body = page.encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()[0]} {self.headers.get('Host', '')} {fmt % args}")


if __name__ == "__main__":
    host = os.environ.get("BLOCK_HOST", "10.100.0.1")
    port = int(os.environ.get("BLOCK_PORT", "80"))
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"FilterVPN block page on {host}:{port}")
    srv.serve_forever()
