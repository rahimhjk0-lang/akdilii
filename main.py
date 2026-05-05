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
            qs = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            if "crc_token" in qs:
                from urllib.parse import parse_qs, unquote
                params = parse_qs(qs)
                crc_list = params.get("crc_token", [])
                crc = unquote(crc_list[0]) if crc_list else ""
                print(f"[CRC] crc_token={repr(crc)}")
                body = (_json.dumps({"crc_token": crc}, separators=(",", ":"))
                        .encode("utf-8"))
                await send({"type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ]})
                await send({"type": "http.response.body", "body": body})
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
