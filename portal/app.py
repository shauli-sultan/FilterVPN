"""FilterVPN self-service portal (Hebrew, RTL) — open enrollment, no admin code.
CA is downloadable directly from the site.
Run: ENDPOINT=filter-vpn.duckdns.org:51820 uvicorn portal.app:app --port 8000
Behind Caddy with TLS.
"""
import os
import re
import subprocess
import sys
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(BASE, "wireguard", "gen-client.py")
CHANGE = os.path.join(BASE, "wireguard", "change-tier.py")
CLIENTS = os.path.join(BASE, "wireguard", "clients")
ENDPOINT = os.environ.get("ENDPOINT", "filter-vpn.duckdns.org:51820")

# CA locations (repo copy + deployed copy)
CA_CANDIDATES = [
    os.path.join(BASE, "proxy", "ca", "FilterVPN-RootCA.crt"),
    "/opt/filtervpn/proxy/ca/FilterVPN-RootCA.crt",
    "/home/ubuntu/filtervpn/proxy/ca/FilterVPN-RootCA.crt",
]

app = FastAPI(title="FilterVPN")

TIERS_HE = {
    1: "רמה 1 — בסיסי",
    2: "רמה 2 — רגיל",
    3: "רמה 3 — מחמיר",
    4: "רמה 4 — מקסימלי",
}

TIER_DETAILS = {
    1: {
        "icon": "🛡️",
        "title": "רמה 1 — בסיסי",
        "subtitle": "הגנה קלה, גלישה מהירה",
        "color": "#10b981",
        "for_who": "למבוגרים שרוצים הגנה בסיסית",
        "points": [
            "לא רואים אתרי מבוגרים ופורנו",
            "אתרים מסוכנים שמנסים לגנוב סיסמאות נחסמים",
            "החיפוש בגוגל בטוח יותר",
            "האינטרנט נשאר מהיר מאוד",
            "וואטסאפ עובד רגיל",
        ],
        "dns": "קל ומהיר",
    },
    2: {
        "icon": "🔍",
        "title": "רמה 2 — רגיל",
        "subtitle": "מוסיף סינון תמונות",
        "color": "#3b82f6",
        "for_who": "לילדים - מסנן גם תמונות",
        "points": [
            "כל מה שיש ברמה 1",
            "תמונות לא מתאימות נחסמות ומתחלפות בהסבר בעברית",
            "דפים עם מילים לא ראויות נחסמים",
            "צריך להתקין פעם אחת קובץ אבטחה קטן (מורידים כאן למטה)",
        ],
        "dns": "מסנן תמונות",
    },
    3: {
        "icon": "🎯",
        "title": "רמה 3 — מחמיר",
        "subtitle": "יוטיוב בטוח לילדים",
        "color": "#f59e0b",
        "for_who": "ללימודים — יוטיוב נקי",
        "points": [
            "כל מה שיש ברמה 2",
            "יוטיוב עובד רק במצב מוגבל (בלי סרטונים למבוגרים)",
            "החיפוש בגוגל וביוטיוב מסונן",
        ],
        "dns": "יוטיוב מוגבל",
    },
    4: {
        "icon": "🔒",
        "title": "רמה 4 — מקסימלי",
        "subtitle": "בלי רשתות חברתיות",
        "color": "#ef4444",
        "for_who": "למי שרוצה שקט מהרשתות",
        "points": [
            "כל מה שיש ברמה 3",
            "טיקטוק, אינסטגרם, פייסבוק, רדיט, X וסנאפצ'ט חסומים",
            "אם מנסים להיכנס רואים דף הסבר נעים בעברית",
            "וואטסאפ נשאר פתוח לשיחות",
        ],
        "dns": "בלי רשתות חברתיות",
    },
}

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
a.btn-ca{{display:inline-block;background:#f59e0b;color:#fff;border-radius:10px;padding:10px 16px;margin:6px 6px 0 0;text-decoration:none;font-weight:700}}
.nav{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}} .nav a{{text-decoration:none}}
small.mut{{color:var(--mut)}} .mono{{font-family:ui-monospace,Consolas,monospace}} .hr{{height:1px;background:var(--border);margin:16px 0}}
.tier-radio{{display:flex;gap:10px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:10px;margin:6px 0;cursor:pointer}} .tier-radio:has(input:checked){{border-color:var(--pri);background:#f0fdf4}}
.tier-radio input{{width:auto}} .tier-meta{{font-size:12px;color:var(--mut)}}
.ca-box{{background:#fffbeb;border:1px solid #fcd34a;border-radius:12px;padding:12px 14px;margin:12px 0}}
</style></head><body><div class="wrap">{body}</div></body></html>"""

def _tiers_grid(selected=3):
    html = '<div class="grid">'
    for tid in [1,2,3,4]:
        d = TIER_DETAILS[tid]
        points = "".join(f"<li>{p}</li>" for p in d["points"])
        sel = " ⭐ מומלץ" if tid==selected else ""
        html += f"""<div class="card tier" style="--tier:{d['color']}">
<div style="font-size:26px">{d['icon']}</div>
<h3>{d['title']}{sel}</h3>
<div class="sub">{d['subtitle']}</div>
<div style="font-size:13px;color:#0ea5e9;margin:4px 0">{d['for_who']}</div>
<ul>{points}</ul>
</div>"""
    html += "</div>"
    html += """<div class="card" style="margin-top:4px"><b>💡 איך זה עובד? פשוט מאוד</b>
<div class="mut" style="font-size:14px;line-height:1.7;margin-top:6px">
1️⃣ בוחרים רמה כאן באתר ומקבלים קובץ קטן.<br>
2️⃣ מתקינים אפליקציה חינמית בשם <b>WireGuard</b> ופותחים בה את הקובץ (או סורקים קוד).<br>
3️⃣ מפעילים — וזהו! כל האינטרנט במכשיר הזה מסונן לפי הרמה שבחרת.<br>
רוצה לשנות רמה? נכנסים שוב, בוחרים רמה אחרת ומקבלים קובץ חדש — לא צריך למחוק כלום.
</div></div>"""
    return html

def _ca_box():
    return """<div class="ca-box">
<b>📜 קובץ אבטחה לרמות 2 ו-3</b> <span style="font-size:12px;color:#92400e">— רק אם בחרת רמה 2 או 3</span><br>
<small class="mut" style="line-height:1.7">אם בחרת רמה 2 או 3 צריך להתקין פעם אחת קובץ קטן:<br>
<b>אנדרואיד:</b> לחץ הורד → פתח את הקובץ → אשר התקנה.<br>
<b>אייפון:</b> לחץ הורד → פתח את הקובץ → לך להגדרות → אודות → אמון בתעודות → הפעל אמון.</small><br>
<a class="btn-ca" href="/ca.crt" download>⬇️ הורד קובץ אבטחה</a>
</div>"""

def _enroll_form(msg_html=""):
    tiers_opts = "".join(
        f'<label class="tier-radio"><input type="radio" name="tier" value="{tid}" {"checked" if tid==3 else ""}><span><b>{TIER_DETAILS[tid]["title"]}</b><br><span class="tier-meta">{TIER_DETAILS[tid]["subtitle"]} — {d["for_who"]}</span></span></label>'
        for tid, d in TIER_DETAILS.items()
    )
    body = f"""
<div class="hero">
<div class="badge">שירות חינמי לקהילה · פשוט ובטוח</div>
<h1>🛡️ FilterVPN — אינטרנט מסונן בקלות</h1>
<p>בוחרים כמה לסנן, מקבלים קובץ אחד, ומדליקים. בלי סיסמאות ובלי הגדרות מסובכות.</p>
<div class="nav">
<a href="/" class="btn btn-ghost" style="padding:8px 12px">הרשמה</a>
<a href="/change" class="btn btn-ghost" style="padding:8px 12px">🔄 החלפת רמה</a>
<a href="/ca.crt" class="btn btn-ghost" style="padding:8px 12px">📜 קובץ אבטחה</a>
</div>
</div>

<h2 style="margin:18px 0 6px">בחרו כמה לסנן — הסבר פשוט</h2>
{_tiers_grid(selected=3)}

<div class="form-card">
<h2 style="margin:0 0 8px">📝 יצירת חיבור חדש</h2>
<div class="mut" style="font-size:14px">תנו שם למכשיר (למשל: הטלפון-של-אבא, טאבלט-הילדים) ובחרו רמה. תקבלו קובץ וקוד לסריקה — זה הכל.</div>
{msg_html}
<form method="post" action="/enroll">
<label>שם למכשיר (באנגלית, לדוגמה: tablet-yeladim)</label>
<input name="name" required pattern="[A-Za-z0-9_-]+" maxlength="32" placeholder="לדוגמה: phone-abba">
<label>כמה לסנן?</label>
{tiers_opts}
<button class="btn" type="submit">צור קובץ חיבור ✅</button>
</form>
{_ca_box()}
<small class="mut">📱 אחרי זה: התקינו אפליקציה בשם <b>WireGuard</b> (חינם בחנות) → פתחו אותה → לחצו + → בחרו את הקובץ או סרקו את הקוד → הדליקו. זהו!</small>
</div>
"""
    return _layout("הרשמה", body)

def _change_form(msg_html=""):
    tiers_opts = "".join(
        f'<label class="tier-radio"><input type="radio" name="new_tier" value="{tid}" {"checked" if tid==3 else ""}><span><b>{TIER_DETAILS[tid]["title"]}</b><br><span class="tier-meta">{TIER_DETAILS[tid]["subtitle"]}</span></span></label>'
        for tid, d in TIER_DETAILS.items()
    )
    body = f"""
<div class="hero">
<div class="badge">שינוי פשוט</div>
<h1>🔄 רוצים לשנות כמה לסנן?</h1>
<p>בחרו שם שכבר יצרתם ורמה חדשה. תקבלו קובץ חדש — פתחו אותו ב-WireGuard וזה מתעדכן.</p>
<div class="nav">
<a href="/" class="btn btn-ghost" style="padding:8px 12px">← חזרה להרשמה</a>
<a href="/ca.crt" class="btn btn-ghost" style="padding:8px 12px">📜 קובץ אבטחה</a>
</div>
</div>

<div class="form-card">
<h2 style="margin:0 0 8px">החלפת רמה</h2>
<div class="mut" style="font-size:14px">כתבו את אותו שם שנתתם בהרשמה ובחרו רמה חדשה.</div>
{msg_html}
<form method="post" action="/change">
<label>שם המכשיר שיצרתם</label>
<input name="name" required pattern="[A-Za-z0-9_-]+" maxlength="32" placeholder="לדוגמה: phone-abba">
<label>רמה חדשה</label>
{tiers_opts}
<button class="btn btn-secondary" type="submit">עדכן רמה 🔄</button>
</form>
{_ca_box()}
</div>

<div class="card"><small class="mut" style="line-height:1.7">
💡 אחרי שמחליפים רמה, צריך להוריד את הקובץ החדש ולפתוח אותו שוב באפליקציית WireGuard. החיבור הישן מפסיק לעבוד אוטומטית.
</small></div>
"""
    return _layout("החלפת רמה", body)

def _success_page(name, tier_he, ip):
    body = f"""
<div class="hero"><h1>✅ מוכן! הקובץ של {name} נוצר</h1><p>{tier_he} — הכל מוכן להפעלה</p></div>
<div class="card" style="margin-top:16px">
<div class="ok">הורידו את הקובץ או סרקו את הקוד — ואז הדליקו באפליקציה.</div>
<p><a class="btnlink" href="/files/{name}.conf" download="{name}.conf">⬇️ הורד קובץ</a>
<a class="btnlink" href="/files/{name}.png" download="{name}.png">🔳 הורד קוד לסריקה</a>
<a class="btn-ca" href="/ca.crt">📜 קובץ אבטחה (אם צריך)</a></p>
<div class="card" style="background:#f0fdf4;border:1px solid #bbf7d0;margin:12px 0"><b>איך מפעילים? 3 צעדים פשוטים:</b><br>
<small style="line-height:1.8">
1️⃣ התקינו <b>WireGuard</b> מהחנות (אייקון לבן עם מנהרה).<br>
2️⃣ פתחו את WireGuard → לחצו <b>+</b> → בחרו "ייבוא מקובץ" או "סרוק קוד".<br>
3️⃣ לחצו על הכפתור להפעלה — כשזה כחול/ירוק, אתם מוגנים.
</small></div>
<p style="margin-top:14px"><a href="/">← יצירת חיבור נוסף</a> · <a href="/change">שינוי רמה</a></p>
</div>
"""
    return _layout("נרשמת בהצלחה", body)

def _change_success(name, tier_he, ip):
    body = f"""
<div class="hero"><h1>✅ הרמה עודכנה!</h1><p>הקובץ החדש של <b>{name}</b> מוכן — {tier_he}</p></div>
<div class="card" style="margin-top:16px">
<div class="ok">הורידו את הקובץ החדש ופתחו אותו שוב ב-WireGuard. החיבור הישן יפסיק לעבוד.</div>
<p><a class="btnlink" href="/files/{name}.conf" download="{name}.conf">⬇️ הורד קובץ מעודכן</a>
<a class="btnlink" href="/files/{name}.png" download="{name}.png">🔳 קוד מעודכן</a></p>
<p><a href="/">← הרשמה</a> · <a href="/change">עוד שינוי</a></p>
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
    if m:
        return m.group(1)
    m2 = re.search(r"(\d+\.\d+\.\d+\.\d+)", r.stdout)
    return m2.group(1) if m2 else ""

def _find_ca():
    for p in CA_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None

# ── routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return _enroll_form()


@app.get("/change", response_class=HTMLResponse)
def change_get():
    return _change_form()


@app.post("/enroll", response_class=HTMLResponse)
def enroll_form(name: str = Form(...), tier: int = Form(...)):
    if tier not in TIERS_HE or not _valid_name(name):
        return _enroll_form('<div class="err">❌ שם או רמה לא תקינים.</div>')
    try:
        ip = _do_enroll(name, tier)
    except ValueError as e:
        return _enroll_form(f'<div class="err">❌ ההרשמה נכשלה: {e}</div>')
    return _success_page(name, TIERS_HE[tier], ip or "?")


@app.post("/change", response_class=HTMLResponse)
def change_form(name: str = Form(...), new_tier: int = Form(..., alias="new_tier"), keep_keys: str = Form(default="")):
    if new_tier not in TIERS_HE or not _valid_name(name):
        return _change_form('<div class="err">❌ שם או רמה לא תקינים.</div>')
    try:
        ip = _do_change(name, new_tier, keep_keys=bool(keep_keys))
    except ValueError as e:
        return _change_form(f'<div class="err">❌ ההחלפה נכשלה: {e}</div>')
    return _change_success(name, TIERS_HE[new_tier], ip or "?")


@app.get("/ca.crt")
def get_ca():
    p = _find_ca()
    if not p:
        raise HTTPException(404, "CA not found on server — run proxy/ca/gen-ca.sh")
    with open(p, "rb") as f:
        data = f.read()
    return Response(data, media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": "attachment; filename=FilterVPN-RootCA.crt"})

@app.get("/FilterVPN-RootCA.crt")
def get_ca_alias():
    return get_ca()

@app.get("/files/{fname}")
def download_file(fname: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}\.(conf|png)", fname or ""):
        raise HTTPException(400, "bad filename")
    path = os.path.join(CLIENTS, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    # Use octet-stream for .conf so Windows/Chrome don't append .txt (was text/plain → .conf.txt)
    media = "application/octet-stream" if fname.endswith(".conf") else "image/png"
    with open(path, "rb") as f:
        return Response(f.read(), media_type=media,
                        headers={
                            "Content-Disposition": f'attachment; filename="{fname}"',
                            "X-Content-Type-Options": "nosniff",
                        })


class Enroll(BaseModel):
    name: str
    tier: int


@app.post("/api/enroll")
def enroll_api(e: Enroll):
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
def change_api(req: ChangeReq):
    if req.tier not in TIERS_HE or not _valid_name(req.name):
        raise HTTPException(400, "bad name/tier")
    try:
        ip = _do_change(req.name, req.tier, keep_keys=req.keep_keys)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    cpath = os.path.join(CLIENTS, f"{req.name}.conf")
    conf = open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf": conf, "ip": ip, "tier_he": TIERS_HE[req.tier]}
