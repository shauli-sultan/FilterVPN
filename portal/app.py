"""FilterVPN — Premium portal for Jewish teens & adults. No usernames, premade tier configs.
Each download creates a unique WireGuard profile (private IP) — UI shows 4 simple cards.
"""
import base64
import os
import re
import secrets
import subprocess
import sys
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, Response

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(BASE, "wireguard", "gen-client.py")
CLIENTS = os.path.join(BASE, "wireguard", "clients")
ENDPOINT = os.environ.get("ENDPOINT", "filter-vpn.duckdns.org:51820")
CA_CANDIDATES = [
    os.path.join(BASE, "proxy", "ca", "FilterVPN-RootCA.crt"),
    "/opt/filtervpn/proxy/ca/FilterVPN-RootCA.crt",
    "/home/ubuntu/filtervpn/proxy/ca/FilterVPN-RootCA.crt",
]
app = FastAPI(title="FilterVPN")

TIERS_HE = {
    1: "רמה 1 — בסיסי (Basic)",
    2: "רמה 2 — מסונן (Filtered)",
    3: "רמה 3 — מהדרין (Mehadrin)",
    4: "רמה 4 — מהדרין מן המהדרין",
}
TIER_DETAILS = {
    1: {"icon":"🛡️","title":"רמה 1 — בסיסי","en":"Basic","color":"#10b981","for_who":"למבוגרים — הכי פתוח","points":["חוסם רק פורנו/מבוגרים, פישינג ונוזקות","כל השאר פתוח — חדשות, לימוד, עבודה","יוטיוב ורשתות פתוחות","וואטסאפ תמיד פתוח","הכי מהיר"],"dns":"Adult Filter","pool":"10.100.1.x"},
    2: {"icon":"🎬","title":"רמה 2 — מסונן","en":"Filtered","color":"#0ea5e9","for_who":"לנערים ומבוגרים — יוטיוב בטוח","points":["כל מה ברמה 1","יוטיוב במצב מוגבל (Restricted) — בלי תכני מבוגרים","גוגל/בינג SafeSearch","וואטסאפ תמיד פתוח"],"dns":"Adult + YouTube","pool":"10.100.2.x"},
    3: {"icon":"✡️","title":"רמה 3 — מהדרין","en":"Mehadrin","color":"#f59e0b","for_who":"לבחורי ישיבה — בלי קהילות פרוצות","points":["כל מה ברמה 2 + יוטיוב מוגבל","חוסם רדיט, X / טוויטר, אימג׳ור, טאמבלר, 4צ׳אן/8צ׳אן, לייבג׳ורנל","לינקדאין ווואטסאפ פתוחים"],"dns":"Family Filter","pool":"10.100.3.x"},
    4: {"icon":"🔒","title":"רמה 4 — מהדרין מן המהדרין","en":"Mehadrin Min HaMehadrin","color":"#dc2626","for_who":"לנערים צעירים — שקט מוחלט","points":["כל רמה 1 + יוטיוב מוגבל","חוסם פייסבוק, אינסטגרם, טיקטוק, סנאפ׳ט, רדיט, X, דיסקורד, טוויץ׳ ועוד","רק יוטיוב (מוגבל) + לינקדאין + וואטסאפ פתוחים"],"dns":"Family Strict","pool":"10.100.4.x"},
}
def _gen_random_name(): return f"vpn-{secrets.token_hex(4)}"

def _layout(title, body, extra=""):
    return f"""<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — FilterVPN</title>
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700;800&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
{extra}
<style>
:root{{--bg:#f8fafc;--card:#fff;--border:#e2e8f0;--mut:#64748b;--ink:#0f172a;--pri:#0ea5e9;--pri2:#10b981;--radius:18px}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
body{{margin:0;font-family:Heebo,system-ui,Arial;background:var(--bg);color:var(--ink);line-height:1.6}}
a{{color:#0ea5e9;text-decoration:none}} a:hover{{text-decoration:underline}}
.wrap{{max-width:1100px;margin:0 auto;padding:28px 16px}}
.hero{{position:relative;overflow:hidden;background:linear-gradient(135deg,#0f172a 0%,#0ea5e9 55%,#10b981 100%);color:#fff;border-radius:28px;padding:36px 28px;box-shadow:0 20px 40px rgba(2,6,23,.25)}}
.hero::after{{content:"";position:absolute;inset:-1px;background:radial-gradient(600px 200px at 85% 10%, rgba(255,255,255,.22), transparent 60%);pointer-events:none}}
.hero h1{{margin:0;font-size:34px;letter-spacing:-.02em;line-height:1.15}} .hero h1 span{{background:linear-gradient(90deg,#fff, #e0f2fe);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero p{{margin:10px 0 0;max-width:720px;opacity:.92;font-size:16px}}
.badge{{display:inline-flex;gap:8px;align-items:center;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.32);backdrop-filter:blur(8px);padding:6px 12px;border-radius:999px;font-size:12px;font-weight:700}}
.nav{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}} .pill-btn{{display:inline-flex;align-items:center;gap:8px;background:#fff;color:#0f172a;border:1px solid #e2e8f0;padding:10px 14px;border-radius:999px;font-weight:700;box-shadow:0 4px 12px rgba(0,0,0,.08)}}
.pill-btn.primary{{background:#0f172a;color:#fff;border-color:#0f172a}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}} @media(max-width:860px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;box-shadow:0 8px 24px rgba(15,23,42,.05)}}
.card.tier{{position:relative;overflow:hidden;border-top:4px solid var(--tier);transition:transform .18s, box-shadow .18s}} .card.tier:hover{{transform:translateY(-2px);box-shadow:0 14px 30px rgba(15,23,42,.08)}}
.card.tier h3{{margin:6px 0 4px;font-size:18px}} .mut{{color:var(--mut)}} .mono{{font-family:JetBrains Mono,ui-monospace,monospace;font-size:12px}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:12px 16px;border-radius:12px;border:0;background:var(--tier,#0ea5e9);color:#fff;font-weight:800;font-size:15px;cursor:pointer;box-shadow:0 8px 18px rgba(14,165,233,.22);transition:filter .15s, transform .1s}} .btn:hover{{filter:brightness(.98)}} .btn:active{{transform:translateY(1px)}}
.btn.ghost{{background:#fff;color:var(--ink);border:1px solid var(--border);box-shadow:none}}
.btn.dark{{background:#0f172a}}
.kbd{{display:inline-block;border:1px solid #cbd5e1;border-bottom-width:2px;background:#fff;padding:2px 6px;border-radius:6px;font-size:12px}}
.qr{{width:200px;height:200px;border-radius:12px;border:1px solid var(--border);background:#fff;padding:8px}}
.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} @media(max-width:860px){{.steps{{grid-template-columns:1fr}}}}
.step-num{{width:36px;height:36px;border-radius:999px;display:grid;place-items:center;background:#0f172a;color:#fff;font-weight:800}}
.note{{background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:12px}}
@media print{{ .no-print{{display:none !important}} .wrap{{max-width:none;padding:0}} @page{{size:A4 landscape;margin:10mm}} body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}} .card{{break-inside:avoid}} }}
</style></head><body><div class="wrap">{body}</div></body></html>"""

def _tiers_grid():
    h='<div class="grid">'
    for tid in [1,2,3,4]:
        d=TIER_DETAILS[tid]
        pts="".join(f"<li>{p}</li>" for p in d["points"])
        h+=f"""<div class="card tier" style="--tier:{d['color']}">
<div style="font-size:26px">{d['icon']}</div>
<div style="font-size:12px;font-weight:800;letter-spacing:.04em;color:{d['color']}">{d['en']} · {d['pool']}</div>
<h3>{d['title']}</h3>
<div class="mut" style="font-size:13px">{d['for_who']} · {d['dns']}</div>
<ul style="margin:10px 18px 0 0;font-size:14px">{pts}</ul>
</div>"""
    h+='</div>'
    return h

def _download_grid():
    h='<div class="grid">'
    for tid in [1,2,3,4]:
        d=TIER_DETAILS[tid]
        h+=f"""<div class="card" style="border-top:4px solid {d['color']};text-align:center">
<div style="font-size:28px">{d['icon']}</div>
<div style="font-weight:800">{d['title']}</div>
<div class="mut" style="font-size:13px">{d['for_who']}</div>
<form method="post" action="/download/tier/{tid}" style="margin-top:12px">
<button class="btn" style="--tier:{d['color']}" type="submit">⬇️ הורד רמה {tid} — {d['en']}</button>
</form>
<a class="btn ghost" style="margin-top:8px" href="/qr/tier/{tid}" target="_blank">🔳 הצג QR</a>
<div class="mut" style="font-size:11px;margin-top:8px">{d['pool']} · וואטסאפ פתוח</div>
</div>"""
    h+='</div>'
    h+="""<div class="card" style="margin-top:16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;justify-content:space-between">
<div><b>🖨️ להדפסה?</b> <span class="mut">דף אחד עם 4 הקודים לרוחב A4 — לחלק לכל מכשיר.</span></div>
<a class="btn dark no-print" href="/print" target="_blank" style="width:auto;padding:12px 18px">פתח דף הדפסה</a>
</div>"""
    return h

def _main_page(msg=""):
    body=f"""
<div class="hero">
<div class="badge">✡️ לציבור היהודי · לנערים, בחורים ומבוגרים <span style="opacity:.7">·</span> וואטסאפ תמיד פתוח</div>
<h1><span>FilterVPN</span> — אינטרנט נקי בלי סיבוכים</h1>
<p>בלי שמות משתמש ובלי סיסמאות. בוחרים רמה, מורידים קובץ אחד, ומדליקים ב-<b>WireGuard</b>. כל הורדה יוצרת חיבור ייחודי עם IP פרטי — גם ההדפסה יוצרת 4 קבצים נפרדים.</p>
<div class="nav">
<a class="pill-btn primary" href="#download">⬇️ הורדה מהירה</a>
<a class="pill-btn" href="/print" target="_blank">🖨️ דף הדפסה</a>
<a class="pill-btn" href="#how">איך זה עובד</a>
</div>
</div>

<h2 style="margin:22px 0 8px">4 הרמות — בדיוק כמו שהגדרת</h2>
{_tiers_grid()}

<div id="how" class="card" style="margin-top:4px">
<b>איך זה עובד — 3 צעדים פשוטים</b>
<div class="steps" style="margin-top:10px">
<div class="card" style="margin:0"><div class="step-num">1</div><b>בחרו רמה</b><div class="mut" style="font-size:14px">בחרו: <b>בסיסי</b> / <b>מסונן</b> / <b>מהדרין</b> / <b>מהדרין מן המהדרין</b> — ההסבר למעלה.</div></div>
<div class="card" style="margin:0"><div class="step-num">2</div><b>הורידו קובץ + QR</b><div class="mut" style="font-size:14px">כל לחיצה יוצרת קובץ <span class="mono">.conf</span> חדש ו-QR חדש. אין שיתוף מפתח.</div></div>
<div class="card" style="margin:0"><div class="step-num">3</div><b>הדליקו ב-WireGuard</b><div class="mut" style="font-size:14px">התקינו <b>WireGuard</b> (חינם) → <span class="kbd">+</span> → ייבוא / סריקה → הדליקו. זהו!</div></div>
</div>
<div class="note" style="margin-top:12px"><b>הערה חשובה:</b> אם 4 אנשים ישתמשו באותו קובץ — כולם יקבלו אותה כתובת ויתנגשו. לכן כל הורדה כאן יוצרת קובץ חדש. הדפסת 4 הקודים יוצרת גם היא 4 קבצים נפרדים — אחד לכל מכשיר.</div>
</div>

<h2 id="download" style="margin:18px 0 6px">הורדה — 4 קבצים מוכנים</h2>
<div class="mut" style="font-size:14px">לחצו על הרמה הרצויה — תקבלו מיד קובץ ו-QR. אין צורך ברישום.</div>
{msg}
{_download_grid()}

<div class="card" style="margin-top:16px">
<b>מה קורה מאחורי הקלעים?</b> <span class="mut" style="font-size:14px">כל מכשיר מקבל IP לפי רמה <span class="mono">10.100.&lt;רמה&gt;.x</span> — אותה כתובת קובעת את ה-DNS שלו. החסימה היא ברמת ה-DNS (מהיר, בלי פרוקסי איטי) + CleanBrowsing כגיבוי: <span class="mono">1-2 → adult-filter-dns.cleanbrowsing.org (185.228.168.10)</span>, <span class="mono">3-4 → family-filter-dns.cleanbrowsing.org (185.228.168.168)</span>. וואטסאפ, יוטיוב (מוגבל) ולינקדאין נשארים פתוחים ברמה 4.</span>
</div>
"""
    return _layout("FilterVPN — הורדה", body)

def _print_page(items):
    cards="".join(f"""<div style="flex:1;min-width:220px;border:1px solid #e2e8f0;border-radius:16px;padding:14px;text-align:center;background:#fff">
<div style="font-size:22px">{TIER_DETAILS[it['tier']]['icon']}</div>
<div style="font-weight:800">{TIER_DETAILS[it['tier']]['title']}</div>
<div style="font-size:12px;color:#64748b">{TIER_DETAILS[it['tier']]['en']} · {it['ip']}</div>
<img src="data:image/png;base64,{it['qr_b64']}" style="width:190px;height:190px;margin:10px 0;border:1px solid #e2e8f0;border-radius:12px;padding:6px;background:#fff"/>
<div class="mono" style="font-size:11px">{it['name']}.conf</div>
</div>""" for it in items)
    body=f"""
<div class="no-print" style="display:flex;gap:10px;margin-bottom:12px"><a href="/" class="pill-btn" style="background:#fff">← חזרה</a><button onclick="window.print()" class="pill-btn primary">🖨️ הדפס עכשיו</button><span class="mut" style="align-self:center">A4 לרוחב · כל קוד הוא חיבור ייחודי</span></div>
<h1 style="text-align:center;margin:0">FilterVPN — 4 רמות · 4 קודים</h1>
<p style="text-align:center" class="mut">לציבור היהודי · וואטסאפ פתוח בכל הרמות · כל סריקה היא מכשיר נפרד</p>
<div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center">{cards}</div>
<p style="text-align:center;margin-top:14px" class="mut">הורדה נוספת: https://filter-vpn.duckdns.org — בלי שם משתמש</p>
"""
    extra='<style>@media print{ @page{size:A4 landscape;margin:10mm} body{-webkit-print-color-adjust:exact;print-color-adjust:exact} }</style>'
    return _layout("הדפסה — 4 QR", body, extra)

# helpers
def _do_enroll_tier(tier:int):
    name=_gen_random_name()
    r=subprocess.run([sys.executable, GEN, "--tier", str(tier), "--name", name, "--endpoint", ENDPOINT], capture_output=True, text=True)
    if r.returncode!=0: raise ValueError(r.stderr.strip() or r.stdout.strip() or "enroll failed")
    import re
    m=re.search(r"Allocated (\S+)", r.stdout); ip=m.group(1) if m else ""
    pm=re.search(r"PublicKey\s*=\s*(\S+)", r.stdout)
    if pm and ip:
        try: subprocess.run(["sudo","bash", os.path.join(BASE,"wireguard","add-peer.sh"), pm.group(1), f"{ip}/32", name, str(tier)], check=False, capture_output=True)
        except: pass
    return name,ip

def _qr_b64_for_file(conf_path):
    png=conf_path.replace(".conf",".png")
    if not os.path.isfile(png):
        try: subprocess.run(["qrencode","-o",png,"-r",conf_path], check=False)
        except: return ""
    if os.path.isfile(png):
        with open(png,"rb") as f: return base64.b64encode(f.read()).decode()
    return ""

# routes
@app.get("/", response_class=HTMLResponse)
def index(): return _main_page()

@app.post("/download/tier/{tier}", response_class=HTMLResponse)
def download_tier(tier:int):
    if tier not in TIERS_HE: raise HTTPException(400,"bad tier")
    try: name,ip=_do_enroll_tier(tier)
    except ValueError as e: return _main_page(f'<div style="background:#fef2f2;border:1px solid #fecaca;padding:10px;border-radius:10px;color:#991b1b">❌ {e}</div>')
    tier_he=TIERS_HE[tier]
    b64=_qr_b64_for_file(os.path.join(CLIENTS, name+".conf"))
    body=f"""<div class="hero" style="padding:24px"><h1>✅ מוכן! {tier_he}</h1><p>קובץ ייחודי: <span class="mono">{name}.conf · {ip}</span> — כל הורדה היא חיבור חדש</p></div>
<div class="card" style="margin-top:16px;text-align:center">
<div style="background:#ecfdf5;border:1px solid #a7f3d0;padding:10px;border-radius:10px;color:#065f46">הורידו והדליקו ב-WireGuard</div>
<p><a class="btn" style="--tier:{TIER_DETAILS[tier]['color']}" href="/files/{name}.conf" download="{name}.conf">⬇️ הורד קובץ</a></p>
<p><a class="btn ghost" href="/files/{name}.png" download="{name}.png">🔳 הורד QR</a></p>
<div style="margin:12px 0"><img src="data:image/png;base64,{b64}" class="qr" alt="QR"/></div>
<p><a href="/" class="pill-btn">← עוד הורדה</a> <a href="/print" target="_blank" class="pill-btn primary">🖨️ דף הדפסה</a></p>
</div>"""
    return _layout(f"רמה {tier} מוכנה", body)

@app.get("/qr/tier/{tier}")
def qr_preview(tier:int):
    if tier not in TIERS_HE: raise HTTPException(400,"bad tier")
    try: name,ip=_do_enroll_tier(tier)
    except ValueError as e: raise HTTPException(500,str(e))
    png=os.path.join(CLIENTS, f"{name}.png")
    if not os.path.isfile(png): raise HTTPException(500,"qr not found")
    with open(png,"rb") as f: return Response(f.read(), media_type="image/png")

@app.get("/print", response_class=HTMLResponse)
def print_page():
    items=[]
    for tier in [1,2,3,4]:
        try:
            name,ip=_do_enroll_tier(tier)
            b64=_qr_b64_for_file(os.path.join(CLIENTS, f"{name}.conf"))
            items.append({"tier":tier,"name":name,"ip":ip,"qr_b64":b64})
        except Exception as e:
            items.append({"tier":tier,"name":f"error-{tier}","ip":"?","qr_b64":""})
    return _print_page(items)

@app.post("/enroll", response_class=HTMLResponse)
def enroll_form(tier:int=Form(...)):
    if tier not in TIERS_HE: return _main_page('<div class="err">❌ רמה לא תקינה.</div>')
    try: name,ip=_do_enroll_tier(tier)
    except ValueError as e: return _main_page(f'<div class="err">❌ {e}</div>')
    return Response(status_code=303, headers={"Location": f"/files/{name}.conf"})

@app.post("/change", response_class=HTMLResponse)
def change_form(new_tier:int=Form(..., alias="new_tier")):
    if new_tier not in TIERS_HE: return _main_page('<div class="err">❌ רמה לא תקינה.</div>')
    try: name,ip=_do_enroll_tier(new_tier)
    except ValueError as e: return _main_page(f'<div class="err">❌ {e}</div>')
    return Response(status_code=303, headers={"Location": f"/files/{name}.conf"})

@app.get("/ca.crt")
def get_ca():
    for p in CA_CANDIDATES:
        if os.path.isfile(p):
            with open(p,"rb") as f: data=f.read()
            return Response(data, media_type="application/x-x509-ca-cert", headers={"Content-Disposition":"attachment; filename=FilterVPN-RootCA.crt"})
    raise HTTPException(404,"CA not found")

@app.get("/FilterVPN-RootCA.crt")
def get_ca_alias(): return get_ca()

@app.get("/files/{fname}")
def download_file(fname:str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}\.(conf|png)", fname or ""): raise HTTPException(400,"bad filename")
    path=os.path.join(CLIENTS,fname)
    if not os.path.isfile(path): raise HTTPException(404,"not found")
    media="application/octet-stream" if fname.endswith(".conf") else "image/png"
    with open(path,"rb") as f: return Response(f.read(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{fname}"',"X-Content-Type-Options":"nosniff"})

from pydantic import BaseModel
class Enroll(BaseModel): tier:int
@app.post("/api/enroll")
def enroll_api(e:Enroll):
    if e.tier not in TIERS_HE: raise HTTPException(400,"bad tier")
    try: name,ip=_do_enroll_tier(e.tier)
    except ValueError as ex: raise HTTPException(409,str(ex))
    cpath=os.path.join(CLIENTS,f"{e.tier}.conf") if False else os.path.join(CLIENTS, f"{name}.conf")
    conf=open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf":conf,"ip":ip,"tier_he":TIERS_HE[e.tier],"name":name}
class ChangeReq(BaseModel): tier:int
@app.post("/api/change-tier")
def change_api(req:ChangeReq):
    if req.tier not in TIERS_HE: raise HTTPException(400,"bad tier")
    try: name,ip=_do_enroll_tier(req.tier)
    except ValueError as ex: raise HTTPException(409,str(ex))
    cpath=os.path.join(CLIENTS, f"{name}.conf")
    conf=open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf":conf,"ip":ip,"tier_he":TIERS_HE[req.tier],"name":name}
