"""FilterVPN self-service portal (Hebrew, RTL) wrapping wireguard/gen-client.py.
Run: ADMIN_TOKEN=secret ENDPOINT=1.2.3.4:51820 uvicorn portal.app:app --port 8000
Keep on localhost behind TLS reverse proxy; never expose the token endpoint plain.
"""
import os
import re
import subprocess
import sys
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(BASE, "wireguard", "gen-client.py")
CLIENTS = os.path.join(BASE, "wireguard", "clients")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
ENDPOINT = os.environ.get("ENDPOINT", "__PUBLIC_IP__:51820")

app = FastAPI(title="FilterVPN")

TIERS_HE = {
    1: "רמה 1 — בסיסי: חסימת נוזקות, פישינג ואתרי פורנו ומבוגרים",
    2: "רמה 2 — רגיל: כמו רמה 1 + סינון תמונות (דורש התקנת תעודה)",
    3: "רמה 3 — מחמיר: כמו רמה 2 + יוטיוב במצב מוגבל",
    4: "רמה 4 — מקסימלי: כמו רמה 3 + חסימת רשתות חברתיות",
}

PAGE = """<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FilterVPN — הרשמה</title>
<style>body{font-family:Arial,sans-serif;max-width:640px;margin:2em auto;padding:0 1em;background:#f8fafc;color:#111}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:1.5em}
input,select{width:100%;padding:.6em;margin:.3em 0 1em;border:1px solid #cbd5e1;border-radius:8px;font-size:1em}
button{background:#16a34a;color:#fff;border:0;border-radius:8px;padding:.7em 1.5em;font-size:1.1em;cursor:pointer}
.err{background:#fee2e2;border:1px solid #fca5a5;border-radius:8px;padding:.7em;margin-bottom:1em}
.ok{background:#dcfce7;border:1px solid #86efac;border-radius:8px;padding:.7em;margin-bottom:1em}
a.btn{display:inline-block;background:#2563eb;color:#fff;border-radius:8px;padding:.6em 1.2em;margin:.3em;text-decoration:none}
small{color:#64748b}</style></head><body><div class="card">
<h1>🛡️ FilterVPN — הרשמה לשירות הסינון</h1>
{msg}
<form method="post" action="/enroll">
<label>שם משתמש (אותיות ומספרים באנגלית בלבד):</label>
<input name="name" required pattern="[A-Za-z0-9_-]+" maxlength="32">
<label>רמת סינון:</label>
<select name="tier">
<option value="1">רמה 1 — בסיסי: חסימת נוזקות, פישינג ואתרי פורנו</option>
<option value="2">רמה 2 — רגיל: + סינון תמונות (דורש התקנת תעודה)</option>
<option value="3" selected>רמה 3 — מחמיר: + יוטיוב במצב מוגבל</option>
<option value="4">רמה 4 — מקסימלי: + חסימת רשתות חברתיות</option>
</select>
<label>קוד מנהל (מקבלים מהמנהל):</label>
<input name="token" type="password" required>
<button type="submit">הרשמה ✅</button>
</form>
<p><small>📱 אחרי ההרשמה מייבאים את קובץ ההגדרה לאפליקציית WireGuard (או סורקים את קוד ה־QR).
לרמות 2–3 יש להתקין פעם אחת את תעודת האבטחה <b>FilterVPN-RootCA.crt</b> — בקשו אותה מהמנהל.</small></p>
</div></body></html>"""

DONE = """<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>נרשמת בהצלחה</title>
<style>body{font-family:Arial,sans-serif;max-width:640px;margin:2em auto;padding:0 1em;background:#f8fafc;color:#111}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:1.5em}
a.btn{display:inline-block;background:#2563eb;color:#fff;border-radius:8px;padding:.6em 1.2em;margin:.3em;text-decoration:none}
.ok{background:#dcfce7;border:1px solid #86efac;border-radius:8px;padding:.7em;margin-bottom:1em}
small{color:#64748b}</style></head><body><div class="card">
<div class="ok">✅ <b>נרשמת בהצלחה!</b> שם: {name} · {tier} · כתובת: <b>{ip}</b></div>
<p><a class="btn" href="/files/{name}.conf?token={token}">⬇️ הורדת קובץ ההגדרה</a>
<a class="btn" href="/files/{name}.png?token={token}">🔳 הורדת קוד QR</a></p>
<p>1️⃣ התקינו את אפליקציית <b>WireGuard</b> מהחנות.<br>
2️⃣ ייבאו את הקובץ או סרקו את ה־QR.<br>
3️⃣ הפעילו את החיבור — מהרגע הזה הגלישה מסוננת לפי הרמה שנבחרה.</p>
<p><small>רמות 2–3: אל תשכחו להתקין את תעודת האבטחה מהמנהל.</small></p>
<p><a href="/">← חזרה</a></p>
</div></body></html>"""


def _valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name or ""))


def _do_enroll(name: str, tier: int) -> str:
    r = subprocess.run(
        [sys.executable, GEN, "--tier", str(tier), "--name", name, "--endpoint", ENDPOINT],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or r.stdout.strip() or "enroll failed")
    m = re.search(r"Allocated (\S+)", r.stdout)
    return m.group(1) if m else ""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.format(msg="")


@app.post("/enroll", response_class=HTMLResponse)
def enroll_form(name: str = Form(...), tier: int = Form(...), token: str = Form(...)):
    if token != ADMIN_TOKEN:
        return PAGE.format(msg='<div class="err">❌ קוד מנהל שגוי.</div>')
    if tier not in TIERS_HE or not _valid_name(name):
        return PAGE.format(msg='<div class="err">❌ שם או רמה לא תקינים.</div>')
    try:
        ip = _do_enroll(name, tier)
    except ValueError as e:
        return PAGE.format(msg=f'<div class="err">❌ ההרשמה נכשלה: {e}</div>')
    return DONE.format(name=name, tier=TIERS_HE[tier], ip=ip or "?", token=token)


@app.get("/files/{fname}")
def download_file(fname: str, token: str = ""):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "bad token")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}\.(conf|png)", fname or ""):
        raise HTTPException(400, "bad filename")
    path = os.path.join(CLIENTS, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    media = "text/plain" if fname.endswith(".conf") else "image/png"
    with open(path, "rb") as f:
        return Response(f.read(), media_type=media,
                        headers={"Content-Disposition": f"attachment; filename={fname}"})


class Enroll(BaseModel):
    name: str
    tier: int


@app.post("/api/enroll")
def enroll_api(e: Enroll, x_admin_token: str = Header(default="")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "bad token")
    if e.tier not in TIERS_HE or not _valid_name(e.name):
        raise HTTPException(400, "bad name/tier")
    try:
        ip = _do_enroll(e.name, e.tier)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    cpath = os.path.join(CLIENTS, f"{e.name}.conf")
    conf = open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf": conf, "ip": ip, "tier_he": TIERS_HE[e.tier]}
