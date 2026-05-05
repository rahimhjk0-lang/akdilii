import os
import uvicorn
import requests
import threading
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ══════════════════════════════════════════════════════════
# ASGI CRC Middleware — يرد على crc_token قبل أي Router
# ══════════════════════════════════════════════════════════
import json as _json
from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.responses import Response

class CrcMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            qs   = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            path = scope.get("path", "")
            if "crc_token" in qs:
                import hmac, hashlib, re as _re
                from database import SessionLocal
                from models import Carrier

                # استخرج crc_token
                crc = ""
                for part in qs.split("&"):
                    if part.startswith("crc_token="):
                        crc = part.split("=", 1)[1]
                        break

                print(f"[CRC-MIDDLEWARE] path={path} crc_token={repr(crc)}")

                # استخرج merchant_id من الـ path مثل /webhook/yalidine/1
                merchant_id = None
                m = _re.search(r"/webhook/yalidine/(\d+)", path)
                if m:
                    merchant_id = int(m.group(1))

                # جيب API key من DB
                api_key = ""
                try:
                    db = SessionLocal()
                    q  = db.query(Carrier).filter(Carrier.carrier_code == "yalidine", Carrier.is_connected == True)
                    if merchant_id:
                        q = q.filter(Carrier.merchant_id == merchant_id)
                    c = q.first()
                    if c:
                        api_key = c.api_key or ""
                    db.close()
                except Exception as e:
                    print(f"[CRC-MIDDLEWARE] DB error: {e}")

                # احسب HMAC-SHA256
                if api_key and crc:
                    sig = hmac.new(api_key.encode(), crc.encode(), hashlib.sha256).hexdigest()
                    body = _json.dumps({"x-yalidine-signature": sig}).encode()
                    print(f"[CRC-MIDDLEWARE] signature={sig[:20]}...")
                else:
                    # fallback: echo crc_token مباشرة
                    body = _json.dumps({"crc_token": crc}).encode()
                    print(f"[CRC-MIDDLEWARE] fallback echo (no api_key)")

                resp = Response(content=body, status_code=200, media_type="application/json")
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)

from contextlib import asynccontextmanager
from database import init_db
from scheduler import start_scheduler, stop_scheduler
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.admin import router as admin_router
from routes.billing import router as billing_router
from routes.webhook import router as webhook_router

# ==========================================
# Keep-Alive — يمنع Render من النوم
# ==========================================
def keep_alive():
    """ping كل 14 دقيقة باش ما ينامش"""
    time.sleep(60)  # ننتظر دقيقة بعد البدء
    while True:
        try:
            url = os.environ.get("APP_URL", "https://akdilii.onrender.com")
            requests.get(f"{url}/health", timeout=10)
            print("💓 Keep-alive ping")
        except Exception:
            pass
        time.sleep(14 * 60)  # كل 14 دقيقة

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    # شغّل keep-alive في thread منفصل
    t = threading.Thread(target=keep_alive, daemon=True)
    t.start()
    print("🚀 Akdili شغال!")
    yield
    stop_scheduler()

app = FastAPI(
    title    = "Akdili — اكدلي",
    version  = "1.0.0",
    lifespan = lifespan
)

# static folder
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
# تطبيق CRC Middleware
app.add_middleware(CrcMiddleware)


# ── Yalidine Backup Routes ────────────────────────────────
@app.get("/verify_yali_2026")
async def yali_verify(request: Request):
    crc = request.query_params.get("crc_token", "")
    print(f"[VERIFY] crc_token={repr(crc)}")
    return {"crc_token": crc}

# ── Yalidine Webhook Validation (/check) ──────────────────
@app.get("/check")
async def yalidine_check(request: Request):
    crc = request.query_params.get("crc_token", "")
    print(f"[CHECK] crc_token={repr(crc)}")
    return {"crc_token": crc}



# routes
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(billing_router)
app.include_router(webhook_router)

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    token = request.cookies.get("akdili_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/health")
async def health():
    return {"status": "OK", "app": "Akdili"}

# ==========================================
# تشغيل مباشر
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
