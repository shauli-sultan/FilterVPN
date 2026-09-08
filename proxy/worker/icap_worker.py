#!/usr/bin/env python3
"""ICAP RESPMOD worker: image inspection + URL/page word blocking (Tier 2/3).

1. URL word block — adult words in the URL path/query (word boundaries, so
   legit words like "sussex"/"essex" NEVER match "sex"). Allowlisted
   news/edu/gov hosts are exempt.
2. Images (image/*) — NudeNet model when installed, else heuristic fallback.
   Unsafe images are REPLACED with a Hebrew "image blocked" SVG.
3. Page-content word block — visible text of HTML pages (English + Hebrew
   terms). A page is blocked only on REPEATED hits (>= threshold, default 3)
   or an adult <title>, so a news article with a passing mention stays up.
   Allowlisted hosts are exempt.
4. Everything else: pass-through (ICAP 204).

Listens on 127.0.0.1:1344. Squid talks to it (see proxy/squid.conf).
Run: python3 icap_worker.py [--host 127.0.0.1 --port 1344]
Model install (server, one time): pip install -r requirements-ml.txt
Tune: FILTERVPN_WORD_HITS=3 (default), allowlist.txt next to this file.
"""
import argparse
import os
import re
import socket
import threading
from urllib.parse import unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))

# --- URL word block: \b boundaries defeat the Scunthorpe problem ---
# ("sussex", "essex", "asexual" must NOT match "sex")
URL_BLOCK = re.compile(
    r"\b(porn|porno|pornographic|xxx|hentai|henta|ecchi|rule34|"
    r"sex|nude|nudity|nsfw|erotic|escort|playboy|brazzers|bangbros|adult)\b",
    re.I,
)

# --- Page-content word block: English + Hebrew terms ---
CONTENT_BLOCK = re.compile(
    r"(porn|porno|pornographic|pornography|hentai|henta|ecchi|rule34|"
    r"xxx|nsfw|erotic|escort service|"
    r"פורנו|פורנוגרפי|פורנוגרפיה|עירום)",
    re.I,
)

CONTENT_HITS_THRESHOLD = int(os.environ.get("FILTERVPN_WORD_HITS", "3"))
CONTENT_MAX_SCAN = 500_000  # scan at most first 500KB of HTML


def load_allowlist():
    out = set()
    try:
        with open(os.path.join(BASE, "allowlist.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    out.add(line)
    except FileNotFoundError:
        pass
    return out


ALLOWLIST = load_allowlist()
ALLOW_SUFFIXES = (".gov", ".gov.il", ".edu", ".ac.il")


def is_allowlisted(host):
    """News/edu/gov hosts are exempt from WORD blocking (not DNS/image)."""
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    if h in ALLOWLIST or any(h.endswith("." + d) for d in ALLOWLIST):
        return True
    return any(h == s.lstrip(".") or h.endswith(s) for s in ALLOW_SUFFIXES)


def extract_host(text, url):
    try:
        h = urlparse(url).hostname if url else None
        if h:
            return h
    except Exception:
        pass
    m = re.search(r"^Host:\s*(\S+)", text, re.M | re.I)
    return m.group(1).strip() if m else ""


def strip_html(html_text):
    no_script = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_text)
    return re.sub(r"<[^>]+>", " ", no_script)


def url_blocked(url):
    """Adult word (word-boundary) in URL path/query -> Hebrew reason or None."""
    try:
        parts = urlparse(url)
        host = parts.hostname or ""
        if is_allowlisted(host):
            return None
        target = unquote(parts.path + "?" + parts.query)
        if URL_BLOCK.search(target):
            return "כתובת הדף מכילה מילים אסורות"
    except Exception:
        pass
    return None


def content_blocked(html_bytes, host):
    """Repeated adult words in visible page text -> (hits, reason) or None."""
    if is_allowlisted(host):
        return None
    try:
        text = html_bytes[:CONTENT_MAX_SCAN].decode("utf-8", "replace")
    except Exception:
        return None
    title = ""
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if tm:
        title = strip_html(tm.group(1))
    visible = strip_html(text)
    hits = len(CONTENT_BLOCK.findall(visible))
    if title and CONTENT_BLOCK.search(title):
        hits += 2  # adult <title> is a strong signal
    if hits >= CONTENT_HITS_THRESHOLD:
        return hits, f"הדף מכיל מילים אסורות ({hits} מופעים)"
    return None


def block_html(reason):
    return f"""<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<title>התוכן נחסם | FilterVPN</title>
<style>body{{font-family:Arial,sans-serif;background:#f1f5f9;text-align:center;padding:3em 1em}}
.card{{max-width:480px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:2em}}
.reason{{background:#fef3c7;border:1px solid #fcd34a;border-radius:10px;padding:.6em;margin:1em 0;font-weight:bold}}</style>
</head><body><div class="card"><div style="font-size:56px">🚫</div>
<h1>התוכן נחסם</h1><div class="reason">הסיבה: {reason}</div>
<p><small>אם לדעתכם מדובר בטעות, פנו למנהל המערכת.</small></p></div></body></html>""".encode("utf-8")


# Hebrew "image was blocked" replacement (SVG renders inside <img> tags).
BLOCK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400">
<rect width="100%" height="100%" fill="#f1f5f9"/>
<rect x="150" y="60" width="300" height="280" rx="16" fill="#ffffff" stroke="#e2e8f0"/>
<text x="300" y="170" font-size="64" text-anchor="middle">🚫</text>
<text x="300" y="230" font-size="34" text-anchor="middle" fill="#111">התמונה נחסמה</text>
<text x="300" y="270" font-size="20" text-anchor="middle" fill="#64748b">סונן ע״י FilterVPN</text>
</svg>"""

UNSAFE_THRESHOLD = 0.6
_classifier = None
_classifier_failed = False


def classify_nude(img_bytes):
    """Return 'unsafe' score 0..1, or None when no model is available.

    Uses NudeNet (open-source, onnxruntime CPU). First call downloads the
    model (~100-300MB, one time) and warms it up.
    """
    global _classifier, _classifier_failed
    if _classifier_failed:
        return None
    try:
        if _classifier is None:
            from nudenet import NudeClassifier
            _classifier = NudeClassifier()
        import io
        import tempfile
        from PIL import Image
        raw = io.BytesIO(img_bytes)
        Image.open(raw).verify()  # reject corrupt/truncated payloads early
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            Image.open(io.BytesIO(img_bytes)).convert("RGB").save(tmp.name, "JPEG")
            res = _classifier.classify(tmp.name)
        scores = list(res.values())[0]
        return float(scores.get("unsafe", 0.0))
    except ImportError:
        _classifier_failed = True
        print("nudenet not installed — heuristic fallback active (pip install -r requirements-ml.txt)")
        return None
    except Exception as e:
        print(f"classify failed ({e}) — passing image through")
        return None


def icap_response(body: bytes, content_type: str) -> bytes:
    hdr = (f"HTTP/1.1 403 Forbidden\r\nContent-Type: {content_type}\r\n"
           f"Content-Length: {len(body)}\r\n\r\n").encode("latin1")
    full = hdr + body
    return (f"ICAP/1.0 200 OK\r\nEncapsulated: res-hdr=0, res-body={len(hdr)}\r\n\r\n"
            ).encode("latin1") + full


PASS = b"ICAP/1.0 204 No Content Necessary\r\n\r\n"


def handle(conn):
    try:
        data = b""
        conn.settimeout(10)
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 8_000_000:  # cap: don't buffer huge bodies
                break
        head, _, body = data.partition(b"\r\n\r\n")
        text = head.decode("latin1", "replace")
        # Squid health-check: OPTIONS * — must answer 200 with Methods, otherwise Squid marks service down (causes 500 + slow fallback)
        if text.lstrip().startswith("OPTIONS"):
            opts = (
                "ICAP/1.0 200 OK\r\n"
                "Methods: RESPMOD\r\n"
                "Service: FilterVPN RESPMOD\r\n"
                "Options-TTL: 600\r\n"
                "Allow: 204\r\n"
                "Preview: 0\r\n"
                "Transfer-Preview: *\r\n"
                "Max-Connections: 20\r\n"
                "\r\n"
            )
            conn.sendall(opts.encode("latin1"))
            return
        m = re.search(r"Content-Type:\s*([^\r\n;]+)", text, re.I)
        ctype = m.group(1).strip().lower() if m else ""
        um = re.search(r"^(?:GET|POST)\s+(\S+)", text, re.M)
        url = um.group(1) if um else ""
        host = extract_host(text, url)

        reason = url_blocked(url) if url else None
        if reason:
            conn.sendall(icap_response(block_html(reason), "text/html; charset=utf-8"))
        elif ctype.startswith("image/") and body:
            score = classify_nude(body)
            if score is not None:
                blocked = score >= UNSAFE_THRESHOLD
                print(f"image {url[:80]} unsafe={score:.2f} blocked={blocked}")
            else:  # heuristic fallback: big image on a suspicious URL
                blocked = len(body) > 200_000 and bool(URL_BLOCK.search(url + text))
            if blocked:
                conn.sendall(icap_response(BLOCK_SVG.encode("utf-8"), "image/svg+xml"))
            else:
                conn.sendall(PASS)
        elif body and ("html" in ctype or body.lstrip()[:5].lower() == b"<html"):
            hit = content_blocked(body, host)
            if hit:
                _, reason = hit
                conn.sendall(icap_response(block_html(reason), "text/html; charset=utf-8"))
            else:
                conn.sendall(PASS)
        else:
            conn.sendall(PASS)
    except Exception:
        try:
            conn.sendall(PASS)
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
    print(f"ICAP worker on {a.host}:{a.port} (word-hits threshold={CONTENT_HITS_THRESHOLD})")
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
