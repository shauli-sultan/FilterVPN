#!/usr/bin/env python3
"""ICAP RESPMOD worker: image inspection + URL blocking for Tier 2/3.

- Images (image/*): classified by a lightweight open-source nudity model
  (NudeNet via onnxruntime, CPU-friendly) when installed; otherwise a
  URL/size heuristic fallback. Unsafe images are REPLACED with a Hebrew
  "image blocked" SVG so the page layout stays intact.
- Pages/URLs matching porn/hentai/adult regexes: replaced with a Hebrew
  HTML block page explaining the block.
- Everything else: pass-through (ICAP 204).

Listens on 127.0.0.1:1344. Squid talks to it (see proxy/squid.conf).
Run: python3 icap_worker.py [--host 127.0.0.1 --port 1344]
Model install (server, one time): pip install -r requirements-ml.txt
"""
import argparse
import re
import socket
import threading

# Porn / hentai / adult URL regex — mirrors the DNS lists, plus hentai terms.
URL_BLOCK = re.compile(
    r"(porn|porno|xxx|sex|nsfw|nude|hentai|henta|ecchi|rule34|"
    r"escort|playboy|brazzers|bangbros|adult)",
    re.I,
)

BLOCK_HTML = """<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<title>התוכן נחסם | FilterVPN</title>
<style>body{font-family:Arial,sans-serif;background:#f1f5f9;text-align:center;padding:3em 1em}
.card{max-width:480px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:2em}</style>
</head><body><div class="card"><div style="font-size:56px">🚫</div>
<h1>התוכן נחסם</h1><p>התוכן המבוקש סונן על ידי FilterVPN (רמת הסינון שלך).</p>
<p><small>אם לדעתכם מדובר בטעות, פנו למנהל המערכת.</small></p></div></body></html>"""

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
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()  # reject corrupt/truncated payloads early
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
        m = re.search(r"Content-Type:\s*([^\r\n;]+)", text, re.I)
        ctype = m.group(1).strip().lower() if m else ""
        um = re.search(r"^(?:GET|POST)\s+(\S+)", text, re.M)
        url = um.group(1) if um else ""

        if ctype.startswith("image/") and body:
            score = classify_nude(body)
            if score is not None:
                blocked = score >= UNSAFE_THRESHOLD
                print(f"image {url[:80]} unsafe={score:.2f} blocked={blocked}")
            else:  # heuristic fallback: big image on a suspicious URL
                blocked = len(body) > 200_000 and bool(URL_BLOCK.search(url + text))
            if blocked:
                svg = BLOCK_SVG.encode("utf-8")
                conn.sendall(icap_response(svg, "image/svg+xml"))
            else:
                conn.sendall(PASS)
        elif URL_BLOCK.search(url):
            conn.sendall(icap_response(BLOCK_HTML.encode("utf-8"), "text/html; charset=utf-8"))
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
    print(f"ICAP worker on {a.host}:{a.port}")
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
