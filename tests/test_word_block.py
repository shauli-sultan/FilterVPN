#!/usr/bin/env python3
"""Unit tests for word-based blocking: true positives must block, news-like
false positives must pass. Run: python3 tests/test_word_block.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "proxy", "worker"))
import icap_worker as w

CASES_URL = [
    # (url, should_block, why)
    ("http://foo.com/free-porn-videos", True, "porn path"),
    ("http://foo.com/hentai-gallery?page=2", True, "hentai path"),
    ("http://foo.com/xxx-movies", True, "xxx word"),
    ("http://example.com/sussex-news-today", False, "Scunthorpe: sussex"),
    ("http://example.com/essex-council-meeting", False, "Scunthorpe: essex"),
    ("http://example.com/asexual-education", False, "asexual contains sex"),
    ("http://example.com/sports", False, "clean url"),
    ("https://www.ynet.co.il/article/porn-talk-show", False, "allowlisted news host"),
    ("https://sub.bbc.co.uk/news/xxx-mention", False, "allowlisted subdomain"),
]

CASES_CONTENT = [
    # (html bytes, host, should_block, why)
    (b"<html><head><title>best porn sites 2024</title></head><body>list</body></html>",
     "blog.example", True, "adult title on unknown blog"),
    (b"<html><body>" + b"porn " * 5 + b"</body></html>",
     "randomsite.net", True, "repeated words"),
    ("<html><body>פורנו פורנו פורנו תוכן</body></html>".encode("utf-8"),
     "randomsite.net", True, "repeated Hebrew words"),
    (b"<html><body>A new study discusses porn regulation and its effects on teens.</body></html>",
     "randomsite.net", False, "single passing mention"),
    (b"<html><body>The Essex council met today to discuss budgets.</body></html>",
     "randomsite.net", False, "essex not a match"),
    (b"<html><body>Debate over porn regulation continues in parliament today.</body></html>",
     "www.ynet.co.il", False, "allowlisted news host"),
    (b"<html><body>Free hentai gallery with new episodes daily here.</body></html>",
     "randomsite.net", False, "2 hits below threshold of 3"),
]


def main():
    fails = 0
    for url, want, why in CASES_URL:
        got = w.url_blocked(url) is not None
        ok = got == want
        fails += not ok
        print(f"{'OK' if ok else 'FAIL'}: url_blocked blocked={got} want={want} ({why})")
    for html, host, want, why in CASES_CONTENT:
        got = w.content_blocked(html, host) is not None
        ok = got == want
        fails += not ok
        print(f"{'OK' if ok else 'FAIL'}: content_blocked blocked={got} want={want} ({why})")
    print("WORD-BLOCK ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
