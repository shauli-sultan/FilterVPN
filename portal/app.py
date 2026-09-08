"""FilterVPN self-service portal (Hebrew, RTL) wrapping wireguard/gen-client.py.
Run: ADMIN_TOKEN=secret ENDPOINT=1.2.3.4:51820 uvicorn portal.app:app --port 8000
Keep on localhost behind TLS reverse proxy; never expose the token endpoint plain.
"""
import os
import re
import subprocess
import sys
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(BASE, "wireguard", "gen-client.py")
CHANGE = os.path.join(BASE, "wireguard", "change-tier.py")
CLIENTS = os.path.join(BASE, "wireguard", "clients")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
ENDPOINT = os.environ.get("ENDPOINT", "__PUBLIC_IP__:51820")

app = FastAPI(title="FilterVPN")

TIERS_HE = {
    1: "רמה 1 — בסיסי",
    2: "רמה 2 — רגיל",
    3: "רמה 3 — מחמיר",
    4: "רמה 4 — מקסימלי",
}

# Detailed tier info for the nice UI
TIER_DETAILS = {
    1: {
        "icon": "🛡️",
        "title": "רמה 1 — בסיסי",
        "subtitle": "הגנה שקטה, מהירות מלאה",
        "color": "#10b981",
        "for_who": "למי שצריך סינון קל בלי להאט את הגלישה",
        "points": [
            "חסימת אתרי פורנו, האנטאי ותוכן למבוגרים (DNS)",
            "חסימת נוזקות ופישינג",
            "Google SafeSearch מופעל תמיד",
            "יציאה ישירה לאינטרנט — מהיר, בלי פרוקסי",
            "וואטסאפ עובד בכל הרמות",
        ],
        "dns": "CoreDNS :5351",
    },
    2: {
        "icon": "🔍",
        "title": "רמה 2 — רגיל",
        "subtitle": "+ סינון תמונות חכם",
        "color": "#3b82f6",
        "for_who": "לילדים ונוער — מסנן גם תמונות חשודות",
        "points": [
            "כל מה שברמה 1",
            "סינון תמונות וכתובות חשודות (Squid + ICAP)",
            "תמונות לא ראויות מוחלפות באיור בעברית",
            "עמודי אינטרנט עם מילים אסורות נחסמים",
            "דורש התקנת תעודת FilterVPN-RootCA פעם אחת",
        ],
        "dns": "CoreDNS :5352 → פרוקסי :3128/:3129",
    },
    3: {
        "icon": "🎯",
        "title": "רמה 3 — מחמיר",
        "subtitle": "+ יוטיוב מוגבל",
        "color": "#f59e0b",
        "for_who": "לסביבה חינוכית — יוטיוב נקי",
        "points": [
            "כל מה שברמה 2",
            "יוטיוב במצב מוגבל (Restricted Mode) — CNAME ל-restrict.youtube.com",
            "חיפוש גוגל מוגבל — forcesafesearch.google.com",
            "אפליקציות (YouTube/IG/TikTok) מוחלשות ברמת DNS בלבד",
        ],
        "dns": "CoreDNS :5353 + פרוקסי",
    },
    4: {
        "icon": "🔒",
        "title": "רמה 4 — מקסימלי",
        "subtitle": "סביבה סגורה",
        "color": "#ef4444",
        "for_who": "לסביבה עם משמעת רשת גבוהה",
        "points": [
            "כל מה שברמה 3",
            "חסימת רשתות חברתיות: טיקטוק, אינסטגרם, פייסבוק, רדיט, X, סנאפצ'ט",
            "החסימה מוסברת בעמוד חסימה בעברית (10.100.0.1)",
            "יציאה ישירה (בלי פרוקסי) — מהיר",
            "וואטסאפ נשאר פתוח",
        ],
        "dns": "CoreDNS :5354 (סינון חברתי) — ישיר",
    },
}

# ── Shared styles / layout ──────────────────────────────────────────────
def _layout(title, body):
    return f"""<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — FilterVPN</title>
<style>
:root{{--bg:#f8fafc;--card:#ffffff;--border:#e2e8f0;--mut:#64748b;--pri:#16a34a;--pri2:#0ea5e9}}
*{{box-sizing:border-box}} body{{font-family:'Segoe UI',system-ui,Arial,sans-serif;background:var(--bg);color:#0f172a;margin:0}}
a{{color:#2563eb}} .wrap{{max-width:900px;margin:0 auto;padding:24px 16px}}
.hero{{background:linear-gradient(135deg,#0ea5e9 0%,#16a34a 100%);color:#fff;border-radius:20px;padding:28px 24px;position:relative;overflow:hidden}}
.hero h1{{margin:0 0 6px;font-size:28px}} .hero p{{margin:0;opacity:.92;line-height:1.5}}
.badge{{display:inline-block;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.35);padding:4px 10px;border-radius:999px;font-size:12px;margin-bottom:10px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}} @media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px 16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.card.tier{{border-top:4px solid var(--tier)}}
.card.tier h3{{margin:6px 0 4px;font-size:18px}} .card.tier .sub{{color:var(--mut);font-size:13px;margin-bottom:8px}}
.card.tier ul{{margin:8px 0 0;padding:0 18px 0 0;font-size:14px;line-height:1.6}} .card.tier ul li{{margin:2px 0}}
.pill{{display:inline-block;font-size:11px;padding:3px 8px;border-radius:999px;background:#f1f5f9;border:1px solid var(--border);color:var(--mut)}}
.form-card{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:20px;margin-top:18px}}
label{{display:block;font-weight:600;margin:10px 0 6px;font-size:14px}} input,select{{width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:10px;font-size:15px;background:#fff}}
input:focus,select:focus{{outline:2px solid #93c5fd;border-color:#93c5fd}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media(max-width:640px){{.row{{grid-template-columns:1fr}}}}
.btn{{display:inline-block;background:var(--pri);color:#fff;border:0;border-radius:10px;padding:11px 18px;font-size:16px;cursor:pointer;font-weight:700;width:100%;margin-top:12px}}
.btn-secondary{{background:#0ea5e9}} .btn-ghost{{background:#fff;color:#0f172a;border:1px solid var(--border)}}
.err{{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:10px;padding:10px 12px;margin:12px 0}}
.ok{{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;border-radius:10px;padding:10px 12px;margin:12px 0}}
a.btnlink{{display:inline-block;background:#2563eb;color:#fff;border-radius:10px;padding:10px 16px;margin:6px 6px 0 0;text-decoration:none;font-weight:700}}
.nav{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}} .nav a{{text-decoration:none}}
small.mut{{color:var(--mut)}} .mono{{font-family:ui-monospace,Consolas,monospace}} .hr{{height:1px;background:var(--border);margin:16px 0}}
.tier-radio{{display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:10px;margin:6px 0;cursor:pointer}} .tier-radio:has(input:checked){{border-color:var(--pri);background:#f0fdf4}}
.tier-radio input{{width:auto}} .tier-meta{{font-size:12px;color:var(--mut)}}
</style></head><body><div class="wrap">{body}</div></body></html>"""

def _tiers_grid(selected=3):
    html = '<div class="grid">'
    for tid in [1,2,3,4]:
        d = TIER_DETAILS[tid]
        points = "".join(f"<li>{p}</li>" for p in d["points"])
        sel = " 🟢 נבחר כברירת מחדל" if tid==selected else ""
        html += f"""<div class="card tier" style="--tier:{d['color']}">
<div style="font-size:26px">{d['icon']}</div>
<h3>{d['title']}{sel}</h3>
<div class="sub">{d['subtitle']} · {d['for_who']}</div>
<ul>{points}</ul>
<div style="margin-top:10px"><span class="pill">{d['dns']}</span></div>
</div>"""
    html += "</div>"
    html += """<div class="card" style="margin-top:4px"><b>ℹ️ איך זה עובד?</b>
<div class="mut" style="font-size:14px;line-height:1.6;margin-top:6px">
כל מכשיר מקבל כתובת VPN לפי הרמה: <span class="mono">10.100.⟨רמה⟩.x</span> — אותה כתובת קובעת את ה-DNS והפרוקסי שלו אוטומטית.
החלפת רמה = מעבר לכתובת חדשה בטווח של הרמה החדשה + קובץ הגדרות חדש. אין צורך להגדיר כלום במכשיר מעבר לייבוא הקובץ.
<span class="mono">pool .10–.250</span> היום, ניתן להרחבה ל-<span class="mono">/20</span> בלי למספר מחדש.
</div></div>"""
    return html

def _enroll_form(msg_html=""):
    tiers_opts = "".join(
        f'<label class="tier-radio"><input type="radio" name="tier" value="{tid}" {"checked" if tid==3 else ""}><span><b>{TIER_DETAILS[tid]["title"]}</b><br><span class="tier-meta">{TIER_DETAILS[tid]["subtitle"]} — {TIER_DETAILS[tid]["dns"]}</span></span></label>'
        for tid in [1,2,3,4]
    )
    body = f"""
<div class="hero">
<div class="badge">ירושלים · il-jerusalem-1 · filter-vpn.duckdns.org</div>
<h1>🛡️ FilterVPN — שירות הסינון הקהילתי</h1>
<p>VPN מבוסס WireGuard לרשת מסוננת לפי רמות — בלי להגדיר כל מכשיר בנפרד. בוחרים רמה, מקבלים קובץ, מתחברים — וכל הגלישה מסוננת ברמת הרשת.</p>
<div class="nav">
<a href="/" class="btn btn-ghost" style="padding:8px 12px">הרשמה</a>
<a href="/change" class="btn btn-ghost" style="padding:8px 12px">🔄 החלפת רמה</a>
<a href="https://filter-vpn.duckdns.org" class="btn btn-ghost" style="padding:8px 12px">בדיקת חיבור</a>
</div>
</div>

<h2 style="margin:18px 0 6px">השוואת רמות סינון</h2>
{_tiers_grid(selected=3)}

<div class="form-card">
<h2 style="margin:0 0 8px">📝 הרשמה — קבלת קובץ WireGuard</h2>
<div class="mut" style="font-size:14px">שם באנגלית בלבד (אותיות/מספרים/מקף), בחר רמה והזן קוד מנהל. בסיום תקבל קובץ <span class="mono">.conf</span> וקוד QR.</div>
{msg_html}
<form method="post" action="/enroll">
<label>שם משתמש</label>
<input name="name" required pattern="[A-Za-z0-9_-]+" maxlength="32" placeholder="לדוגמה: moshe01">
<label>בחר רמת סינון</label>
{tiers_opts}
<label>קוד מנהל</label>
<input name="token" type="password" required placeholder="קוד שקיבלת מהמנהל">
<button class="btn" type="submit">הרשמה וקבלת קובץ ✅</button>
</form>
<div class="hr"></div>
<small class="mut">📱 אחרי ההרשמה: התקן WireGuard מהחנות → ייבא את הקובץ או סרוק QR → הפעל. לרמות 2–3 התקן פעם אחת את <b>FilterVPN-RootCA.crt</b> (בקש מהמנהל) ואשר אמון בתעודה.</small>
</div>

<div class="card" style="margin-top:16px">
<b>🔒 פרטיות ומגבלות</b><br>
<small class="mut" style="line-height:1.6">
• עד ~500 משתמשים בו-זמנית על שרת ה-Always-Free (2 OCPU/12GB). מעבר לכך — הוספת שרתים.<br>
• אפליקציות עם אבטחת תעודה (YouTube/IG/TikTok) נאכפות ברמת DNS ומועברות ללא פענוח.<br>
• HTTPS לאתרים חסומים יציג שגיאת חיבור (בלי MITM); HTTP יציג עמוד חסימה בעברית.
</small>
</div>
"""
    return _layout("הרשמה", body)

def _change_form(msg_html=""):
    tiers_opts = "".join(
        f'<label class="tier-radio"><input type="radio" name="new_tier" value="{tid}" {"checked" if tid==3 else ""}><span><b>{TIER_DETAILS[tid]["title"]}</b><br><span class="tier-meta">{TIER_DETAILS[tid]["subtitle"]}</span></span></label>'
        for tid in [1,2,3,4]
    )
    body = f"""
<div class="hero">
<div class="badge">ניהול משתמש קיים</div>
<h1>🔄 החלפת רמת סינון</h1>
<p>הרמה אינה קבועה — אפשר לעבור בין רמות בכל עת. המעבר מקצה כתובת חדשה וקובץ הגדרות חדש (יש לייבא מחדש ב-WireGuard).</p>
<div class="nav">
<a href="/" class="btn btn-ghost" style="padding:8px 12px">← חזרה להרשמה</a>
</div>
</div>

<div class="form-card">
<h2 style="margin:0 0 8px">החלפת רמה למשתמש קיים</h2>
<div class="mut" style="font-size:14px">הזן את שם המשתמש הקיים, קוד מנהל, ובחר את הרמה החדשה.</div>
{msg_html}
<form method="post" action="/change">
<label>שם משתמש קיים</label>
<input name="name" required pattern="[A-Za-z0-9_-]+" maxlength="32" placeholder="moshe01">
<label>רמה חדשה</label>
{tiers_opts}
<label>קוד מנהל</label>
<input name="token" type="password" required>
<div class="row">
<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" name="keep_keys" value="1"> שמור מפתחות (אותו קובץ, רק כתובת משתנה — מתקדם)</label>
</div>
<button class="btn btn-secondary" type="submit">החלפת רמה 🔄</button>
</form>
</div>

<h3 style="margin:18px 0 8px">מה קורה בהחלפה?</h3>
<div class="card"><small class="mut" style="line-height:1.7">
• המשתמש עובר מטווח <span class="mono">10.100.⟨ישן⟩.x</span> ל-<span class="mono">10.100.⟨חדש⟩.x</span>.<br>
• קובץ ה-<span class="mono">.conf</span> וה-QR החדשים נוצרים אוטומטית — יש להוריד ולייבא מחדש.<br>
• החיבור הישן נחסם מיד (ה-peer הישן נמחק מ-<span class="mono">wg0.conf</span> ומהממשק החי).<br>
• אם מסומן “שמור מפתחות”, ה-PrivateKey נשאר זהה ורק ה-IP משתנה.
</small></div>
"""
    return _layout("החלפת רמה", body)

def _success_page(name, tier_he, ip, token):
    body = f"""
<div class="hero"><h1>✅ נרשמת בהצלחה!</h1><p>שם: <b>{name}</b> · {tier_he} · כתובת: <span class="mono">{ip}</span></p></div>
<div class="card" style="margin-top:16px">
<div class="ok">הקובץ וה-QR מוכנים — הורד וייבא ל-WireGuard.</div>
<p><a class="btnlink" href="/files/{name}.conf?token={token}">⬇️ הורדת קובץ ההגדרה</a>
<a class="btnlink" href="/files/{name}.png?token={token}">🔳 הורדת קוד QR</a></p>
<div class="hr"></div>
<p style="line-height:1.7">
1️⃣ התקן את <b>WireGuard</b> מהחנות.<br>
2️⃣ ייבא את הקובץ או סרוק את ה-QR.<br>
3️⃣ הפעל — הגלישה מסוננת לפי הרמה.
</p>
<small class="mut">רמות 2–3: התקן את FilterVPN-RootCA.crt וסמוך על התעודה.</small>
<p style="margin-top:14px"><a href="/">← חזרה</a> · <a href="/change">החלפת רמה</a></p>
</div>
"""
    return _layout("נרשמת בהצלחה", body)

def _change_success(name, tier_he, ip, token):
    body = f"""
<div class="hero"><h1>🔄 הרמה הוחלפה בהצלחה!</h1><p>שם: <b>{name}</b> · {tier_he} · כתובת חדשה: <span class="mono">{ip}</span></p></div>
<div class="card" style="margin-top:16px">
<div class="ok">יש להוריד את הקובץ החדש ולייבא מחדש — החיבור הישן כבר לא תקף.</div>
<p><a class="btnlink" href="/files/{name}.conf?token={token}">⬇️ הורדת קובץ מעודכן</a>
<a class="btnlink" href="/files/{name}.png?token={token}">🔳 QR מעודכן</a></p>
<p><a href="/">← הרשמה</a> · <a href="/change">החלפה נוספת</a></p>
</div>
"""
    return _layout("הוחלף", body)

# ── helpers ──────────────────────────────────────────────────────────

def _valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name or ""))


def _do_enroll(name: str, tier: int) -> str:
    r = subprocess.run(
        [sys.executable, GEN, "--tier", str(tier), "--name", name, "--endpoint", ENDPOINT],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or r.stdout.strip() or "enroll failed")
    m = re.search(r"Allocated (\S+)", r.stdout)
    ip = m.group(1) if m else ""
    # hot-add peer to live wg0
    # GEN prints peer block but does not add it; we add via change-tier logic or add-peer
    # Extract pubkey from output and call add-peer
    pm = re.search(r"PublicKey\s*=\s*(\S+)", r.stdout)
    if pm and ip:
        try:
            subprocess.run(["sudo", "bash", os.path.join(BASE, "wireguard", "add-peer.sh"), pm.group(1), f"{ip}/32", name, str(tier)], check=False, capture_output=True)
        except Exception:
            pass
    return ip


def _do_change(name: str, new_tier: int, keep_keys: bool = False) -> str:
    cmd = [sys.executable, CHANGE, "--name", name, "--tier", str(new_tier), "--endpoint", ENDPOINT, "--apply"]
    if keep_keys:
        cmd.append("--keep-keys")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or r.stdout.strip() or "change failed")
    m = re.search(r"->\s+(\S+)\s+\(tier", r.stdout)
    # fallback: find new IP in output
    if m:
        return m.group(1)
    m2 = re.search(r"(\d+\.\d+\.\d+\.\d+)", r.stdout)
    return m2.group(1) if m2 else ""


# ── routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return _enroll_form()


@app.get("/change", response_class=HTMLResponse)
def change_get():
    return _change_form()


@app.post("/enroll", response_class=HTMLResponse)
def enroll_form(name: str = Form(...), tier: int = Form(...), token: str = Form(...)):
    if token != ADMIN_TOKEN:
        return _enroll_form('<div class="err">❌ קוד מנהל שגוי.</div>')
    if tier not in TIERS_HE or not _valid_name(name):
        return _enroll_form('<div class="err">❌ שם או רמה לא תקינים.</div>')
    try:
        ip = _do_enroll(name, tier)
    except ValueError as e:
        return _enroll_form(f'<div class="err">❌ ההרשמה נכשלה: {e}</div>')
    return _success_page(name, TIERS_HE[tier], ip or "?", token)


@app.post("/change", response_class=HTMLResponse)
def change_form(name: str = Form(...), new_tier: int = Form(..., alias="new_tier"), token: str = Form(...), keep_keys: str = Form(default="")):
    if token != ADMIN_TOKEN:
        return _change_form('<div class="err">❌ קוד מנהל שגוי.</div>')
    if new_tier not in TIERS_HE or not _valid_name(name):
        return _change_form('<div class="err">❌ שם או רמה לא תקינים.</div>')
    try:
        ip = _do_change(name, new_tier, keep_keys=bool(keep_keys))
    except ValueError as e:
        return _change_form(f'<div class="err">❌ ההחלפה נכשלה: {e}</div>')
    return _change_success(name, TIERS_HE[new_tier], ip or "?", token)


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


class ChangeReq(BaseModel):
    name: str
    tier: int
    keep_keys: bool = False


@app.post("/api/change-tier")
def change_api(req: ChangeReq, x_admin_token: str = Header(default="")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "bad token")
    if req.tier not in TIERS_HE or not _valid_name(req.name):
        raise HTTPException(400, "bad name/tier")
    try:
        ip = _do_change(req.name, req.tier, keep_keys=req.keep_keys)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    cpath = os.path.join(CLIENTS, f"{req.name}.conf")
    conf = open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf": conf, "ip": ip, "tier_he": TIERS_HE[req.tier]}
