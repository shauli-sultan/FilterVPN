"""Self-service portal wrapping wireguard/gen-client.py.
Run: ADMIN_TOKEN=secret ENDPOINT=1.2.3.4:51820 uvicorn portal.app:app --port 8000
POST /api/enroll {name, tier} with header X-Admin-Token -> returns .conf text + paths.
GET / -> minimal HTML form (manual-share friendly).
"""
import os, subprocess, sys
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(BASE, "wireguard", "gen-client.py")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
ENDPOINT = os.environ.get("ENDPOINT", "__PUBLIC_IP__:51820")

app = FastAPI(title="FilterVPN enroll")

class Enroll(BaseModel):
    name: str
    tier: int

@app.get("/", response_class=HTMLResponse)
def index():
    return """<html><body><h1>FilterVPN enroll</h1>
<form method=post action=/api/enroll-ui>
Name: <input name=name><br>Tier (1-4): <input name=tier><br>
Token: <input name=token type=password><br><button>Enroll</button></form>
<p>Tier 2/3 also need the Root CA (ask admin for FilterVPN-RootCA.crt).</p>
</body></html>"""

@app.post("/api/enroll")
def enroll(e: Enroll, x_admin_token: str = Header(default="")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "bad token")
    if e.tier not in (1, 2, 3, 4) or not e.name.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "bad name/tier")
    r = subprocess.run([sys.executable, GEN, "--tier", str(e.tier), "--name", e.name, "--endpoint", ENDPOINT],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(409, r.stderr or r.stdout)
    cpath = os.path.join(BASE, "wireguard", "clients", f"{e.name}.conf")
    conf = open(cpath).read() if os.path.exists(cpath) else ""
    return {"conf": conf, "log": r.stdout}
