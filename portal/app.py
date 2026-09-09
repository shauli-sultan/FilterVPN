"""WayGuard — DoT portal for Jewish teens & adults. No WireGuard, premade DoT hostnames.
Each tier is a hostname on :853 via SNI. No usernames, no registration.
"""
import base64
import io
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

app = FastAPI(title="WayGuard")

TIERS = {
    1: {"id":1, "en":"Basic — בסיסי", "he":"בסיסי", "color":"#10b981", "icon":"🛡️", "host":"yishiva-basic.duckdns.org", "points":["Blocks only porn/adult, phishing, malware","Everything else open","WhatsApp always open","Fastest"]},
    2: {"id":2, "en":"Filtered — מסונן", "he":"מסונן", "color":"#0ea5e9", "icon":"🎬", "host":"yishiva-filtered.duckdns.org", "points":["Everything in Basic","YouTube Restricted Mode (SafeSearch)","Google/Bing SafeSearch","WhatsApp always open"]},
    3: {"id":3, "en":"Mehadrin — מהדרין", "he":"מהדרין", "color":"#f59e0b", "icon":"✡️", "host":"yishiva-mehadrin.duckdns.org", "points":["Everything in Filtered","Blocks mixed-content: Reddit, X/Twitter, Imgur, Tumblr, 4chan/8chan, LiveJournal","LinkedIn & WhatsApp stay open"]},
    4: {"id":4, "en":"Mehadrin Min HaMehadrin — מהדרין מן המהדרין", "he":"מהדרין מן המהדרין", "color":"#dc2626", "icon":"🔒", "host":"yishiva-super.duckdns.org", "points":["Strict social + YouTube Restricted + Basic","Blocks Facebook, Instagram, TikTok, Snapchat, Reddit, X, Discord, Twitch etc.","Only YouTube (Restricted) + LinkedIn + WhatsApp open"]},
}

def _qr_b64(text: str) -> str:
    try:
        import qrcode
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        # fallback: try qrencode CLI
        import subprocess, tempfile, os
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                subprocess.run(["qrencode", "-o", tmp.name, text], check=True)
                with open(tmp.name, "rb") as f:
                    return base64.b64encode(f.read()).decode()
        except: return ""

def _layout(title, body, extra=""):
    return f"""<!DOCTYPE html><html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — WayGuard</title>
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;700;800&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
{extra}
<style>
:root{{--bg:#f8fafc;--card:#fff;--border:#e2e8f0;--mut:#64748b;--ink:#0f172a}}
*{{box-sizing:border-box}} body{{margin:0;font-family:Heebo,system-ui;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:1100px;margin:0 auto;padding:28px 16px}}
.hero{{background:linear-gradient(135deg,#0f172a 0%,#0ea5e9 55%,#10b981 100%);color:#fff;border-radius:28px;padding:36px 28px;position:relative;overflow:hidden}}
.hero h1{{margin:0;font-size:32px}} .hero p{{opacity:.9;max-width:760px}}
.badge{{display:inline-block;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);padding:6px 12px;border-radius:999px;font-size:12px;font-weight:700}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}} @media(max-width:860px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:18px;box-shadow:0 8px 24px rgba(15,23,42,.06)}}
.card.tier{{border-top:4px solid var(--tier)}} .mono{{font-family:JetBrains Mono,monospace;font-size:12px;background:#f1f5f9;padding:2px 6px;border-radius:6px}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:12px;border-radius:12px;border:0;background:var(--tier,#0ea5e9);color:#fff;font-weight:800;cursor:pointer;text-decoration:none}}
.btn.ghost{{background:#fff;color:var(--ink);border:1px solid var(--border)}} .btn.dark{{background:#0f172a}}
.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}} @media(max-width:860px){{.steps{{grid-template-columns:1fr}}}}
.qr{{width:200px;height:200px;border:1px solid var(--border);border-radius:12px;padding:8px;background:#fff}}
@media print{{.no-print{{display:none}} @page{{size:A4 landscape;margin:10mm}}}}
</style></head><body><div class="wrap">{body}</div></body></html>"""

def _tiers_grid():
    h='<div class="grid">'
    for tid in [1,2,3,4]:
        d=TIERS[tid]
        pts="".join(f"<li>{p}</li>" for p in d["points"])
        h+=f"""<div class="card tier" style="--tier:{d['color']}">
<div style="font-size:26px">{d['icon']}</div>
<div style="font-size:11px;font-weight:800;color:{d['color']}">{d['en']}</div>
<h3>{d['he']} — {d['en'].split(' — ')[0] if ' — ' in d['en'] else d['en']}</h3>
<div class="mono">{d['host']}</div>
<ul style="margin:10px 18px 0 0;font-size:14px">{pts}</ul>
</div>"""
    h+='</div>'
    return h

def _download_grid():
    h='<div class="grid">'
    for tid in [1,2,3,4]:
        d=TIERS[tid]
        host=d['host']
        qr=_qr_b64(host)
        h+=f"""<div class="card" style="border-top:4px solid {d['color']};text-align:center">
<div style="font-size:24px">{d['icon']}</div>
<div style="font-weight:800">{d['he']}</div>
<div style="font-size:13px;color:#64748b;margin:4px 0">{d['points'][0]}</div>
<div class="mono" style="display:inline-block;margin:8px 0;background:#f1f5f9;padding:6px 10px;border-radius:8px;font-size:13px">{host}</div>
<img src="data:image/png;base64,{qr}" class="qr" alt="QR {host}"/>
<div style="margin-top:12px">
<button class="btn" style="--tier:{d['color']}" onclick="navigator.clipboard.writeText('{host}'); this.textContent='הועתק ✓'; setTimeout(()=>this.textContent='העתק כתובת',1500)">📋 העתק כתובת</button>
</div>
<div style="font-size:11px;color:#64748b;margin-top:8px">הדבק בהגדרות → וואטסאפ נשאר פתוח</div>
</div>"""
    h+='</div>'
    h+='<div class="card" style="text-align:center;margin-top:16px"><a class="btn dark" href="/print" target="_blank">🖨️ הדפס דף עם 4 הקודים (A4 לרוחב)</a><div style="font-size:13px;color:#64748b;margin-top:8px">כל קוד הוא רמה אחרת — לחלק למשפחה או לכיתה. אין צורך בהרשמה.</div></div>'
    return h

def _instructions():
    return """<div class="card" style="margin-top:16px">
<h3>📱 איך מגדירים? בחרו את המכשיר שלכם:</h3>
<div class="grid" style="grid-template-columns:repeat(3,1fr)">
<div class="card" style="margin:0;text-align:center"><div style="font-size:28px">🤖</div><b>אנדרואיד</b><div style="font-size:14px;color:#475569;margin-top:6px">הגדרות → רשת ואינטרנט → <b>DNS פרטי</b> → בחרו <b>שם מארח של ספק פרטי</b> → הדביקו את הכתובת שבחרתם → שמור</div><div style="margin-top:8px;font-size:12px;color:#0ea5e9">לדוגמה: yishiva-mehadrin.duckdns.org</div></div>
<div class="card" style="margin:0;text-align:center"><div style="font-size:28px">🍎</div><b>אייפון / אייפד</b><div style="font-size:14px;color:#475569;margin-top:6px">הגדרות → <b>Wi-Fi</b> → לחצו על הרשת → <b>הגדר DNS</b> → <b>ידני</b> → הוסיפו את הכתובת → שמור</div><div style="margin-top:8px;font-size:12px;color:#0ea5e9">או סרקו את ה-QR למעלה</div></div>
<div class="card" style="margin:0;text-align:center"><div style="font-size:28px">💻</div><b>מחשב (Windows/Mac)</b><div style="font-size:14px;color:#475569;margin-top:6px">הגדרות → רשת → <b>DNS</b> → הוסיפו את הכתובת ובחרו <b>DNS מוצפן (TLS)</b></div><div style="margin-top:8px;font-size:12px;color:#0ea5e9">העתיקו והדביקו — זה הכל!</div></div>
</div>
<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:12px;margin-top:12px;text-align:center"><span style="font-size:18px">✨</span> <b>זהו!</b> האינטרנט מסונן לפי הרמה שבחרתם. <b>וואטסאפ</b> עובד תמיד בכל הרמות.</div>
</div>"""

@app.get("/", response_class=HTMLResponse)
def index():
    body=f"""
<div class="hero">
<div class="badge">✡️ WayGuard — לציבור היהודי · לנערים, בחורים ומבוגרים</div>
<h1>WayGuard — אינטרנט מסונן ב-DNS פרטי</h1>
<p>בלי VPN ובלי אפליקציה. בוחרים רמה, מעתיקים כתובת אחת, ומדביקים ב-DNS הפרטי של המכשיר. 4 רמות מהדרין — מבסיסי ועד מהדרין מן המהדרין. וואטסאפ תמיד פתוח.</p>
</div>
<h2 style="margin:18px 0 6px">4 הרמות — בחרו כמה לסנן</h2>
{_tiers_grid()}
{_instructions()}
<h2 id="download" style="margin:18px 0 6px">הורדה — 4 כתובות מוכנות</h2>
<p style="color:#64748b;font-size:14px">סרוק QR או העתק כתובת — אין צורך בקובץ.</p>
{_download_grid()}
"""
    return _layout("WayGuard — הורדה", body)

@app.get("/print", response_class=HTMLResponse)
def print_page():
    cards=""
    for tid in [1,2,3,4]:
        d=TIERS[tid]
        host=d['host']
        qr=_qr_b64(host)
        cards+=f"""<div style="flex:1;min-width:220px;border:1px solid #e2e8f0;border-radius:16px;padding:14px;text-align:center;background:#fff">
<div style="font-size:22px">{d['icon']}</div>
<div style="font-weight:800">{d['he']}</div>
<div style="font-size:11px;color:#64748b">{host}</div>
<img src="data:image/png;base64,{qr}" style="width:180px;height:180px;margin:8px 0;border:1px solid #e2e8f0;border-radius:12px;padding:6px"/>
<div style="font-size:10px" class="mono">DoT :853 · {host}</div>
</div>"""
    body=f"""
<div class="no-print" style="display:flex;gap:10px;margin-bottom:12px"><a href="/" style="background:#fff;border:1px solid #e2e8f0;padding:8px 12px;border-radius:999px;text-decoration:none;color:#0f172a">← חזרה</a><button onclick="window.print()" style="background:#0f172a;color:#fff;border:0;padding:8px 14px;border-radius:999px;cursor:pointer">🖨️ הדפס</button></div>
<h1 style="text-align:center;margin:0">WayGuard — 4 רמות · 4 קודים</h1>
<p style="text-align:center;color:#64748b">A4 לרוחב · סרוק לפי רמה · וואטסאפ פתוח בכל הרמות</p>
<div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center">{cards}</div>
<p style="text-align:center;margin-top:12px;color:#64748b">הורדה נוספת: https://filter-vpn.duckdns.org — בלי שם משתמש</p>
"""
    extra='<style>@media print{ @page{size:A4 landscape;margin:10mm} body{-webkit-print-color-adjust:exact}}</style>'
    return _layout("הדפסה — 4 QR", body, extra)

@app.get("/ca.crt")
def get_ca():
    for p in ["/home/ubuntu/filtervpn/proxy/ca/FilterVPN-RootCA.crt","/opt/filtervpn/proxy/ca/FilterVPN-RootCA.crt"]:
        if os.path.isfile(p):
            with open(p,"rb") as f: data=f.read()
            return Response(data, media_type="application/x-x509-ca-cert", headers={"Content-Disposition":"attachment; filename=WayGuard-RootCA.crt"})
    raise HTTPException(404,"CA not found")

@app.get("/files/{fname}")
def download_file(fname: str):
    # Legacy WireGuard endpoint — now returns 410, redirect to DoT hostnames
    raise HTTPException(410, "WireGuard removed — WayGuard is now pure DoT. Use yishiva-*.duckdns.org hostnames on this page.")

@app.get("/health")
def health(): return {"status":"ok","mode":"dot","tiers":4}
