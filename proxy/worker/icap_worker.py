#!/usr/bin/env python3
"""Minimal ICAP RESPMOD worker (heuristic MVP).
Listens on 127.0.0.1:1344, scans image/* bodies > threshold and suspicious
URL patterns, returns 403 block page on match, else passes through.
MVP is heuristic-only (extension/MIME/URL keywords + size). No ML model.
Run: python3 icap_worker.py [--host 127.0.0.1 --port 1344]
"""
import argparse, re

SUSPICIOUS_URL = re.compile(r"(porn|xxx|sex|nsfw|hentai|escort)", re.I)
BLOCK_PAGE = (b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\nContent-Length: 95\r\n\r\n"
              b"<html><body><h1>Blocked by FilterVPN</h1><p>Content filtered (Tier policy).</p></body></html>")

import socket, threading

def handle(conn):
    try:
        data = b""
        conn.settimeout(5)
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 2_000_000:
                break
        head, _, body = data.partition(b"\r\n\r\n")
        text = head.decode("latin1", "replace")
        m = re.search(r"Content-Type:\s*([^\r\n;]+)", text, re.I)
        ctype = (m.group(1).strip().lower() if m else "")
        url = ""
        um = re.search(r"^GET\s+(\S+)", text, re.M)
        if um:
            url = um.group(1)
        blocked = False
        if ctype.startswith("image/") and len(body) > 200_000:
            # Heuristic placeholder: flag oversized images on suspicious URLs only
            if SUSPICIOUS_URL.search(url) or SUSPICIOUS_URL.search(text):
                blocked = True
        elif SUSPICIOUS_URL.search(url):
            blocked = True
        if blocked:
            conn.sendall(b"ICAP/1.0 200 OK\r\nEncapsulated: res-hdr=0, res-body=95\r\n\r\n" + BLOCK_PAGE)
        else:
            # 204 = no modification
            conn.sendall(b"ICAP/1.0 204 No Content Necessary\r\n\r\n")
    except Exception:
        try:
            conn.sendall(b"ICAP/1.0 204 No Content Necessary\r\n\r\n")
        except Exception:
            pass
    finally:
        conn.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1344)
    a = ap.parse_args()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(50)
    print(f"ICAP worker on {a.host}:{a.port}")
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
