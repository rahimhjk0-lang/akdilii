import os
import uvicorn
import requests
import threading
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp

# ── Imports للـ Routers ──────────────────────────────────
from routes.auth      import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.admin     import router as admin_router
from routes.billing   import router as billing_router
from routes.webhook   import router as webhook_router


# ══════════════════════════════════════════════════════════
# ASGI CRC Middleware — يرد على crc_token قبل أي Router
# ══════════════════════════════════════════════════════════
class CrcMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from urllib.parse import parse_qs, unquote
            qs     = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            params = parse_qs(qs)

            crc_list = params.get("crc_token", [])
            crc      = unquote(crc_list[0]) if crc_list else ""

            if crc:
                print(f"[CRC] crc_token={repr(crc)}")
                body = crc.encode("utf-8")
                await send({"type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type",   b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()),
                            ]})
                await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)


# ══════════════════════════════════════════════════════════
# إنشاء التطبيق
# ══════════════════════════════════════════════════════════
app = FastAPI(title="Akdili", version="1.0")

# أضف Middleware بعد إنشاء app
app.add_middleware(CrcMiddleware)

# ══════════════════════════════════════════════════════════
# Exception Handler — 401 يحول لـ /login بدل JSON
# ══════════════════════════════════════════════════════════
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == 401:
        # API endpoints ترجع JSON، باقي الصفحات تحول لـ /login
        if request.url.path.startswith("/api/"):
            return _JSONResponse({"detail": "Unauthorized"}, status_code=401)
        # احذف cookie قديم + حول لـ /login
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie("akdili_token")
        return response
    # باقي الأخطاء — رجّع JSON عادي
    return _JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# ══════════════════════════════════════════════════════════
# قاعدة البيانات
# ══════════════════════════════════════════════════════════
from database import init_db
init_db()

# ══════════════════════════════════════════════════════════
# Routers
# ══════════════════════════════════════════════════════════
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(billing_router)
app.include_router(webhook_router)

templates = Jinja2Templates(directory="templates")

# ══════════════════════════════════════════════════════════
# Routes أساسية
# ══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    token = request.cookies.get("akdili_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/health")
async def health():
    return {"status": "OK", "app": "Akdili"}

@app.get("/debug-db")
async def debug_db():
    """يختبر اتصال DB ويرجع النتيجة"""
    try:
        from database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
        from config import DATABASE_URL
        safe_url = DATABASE_URL[:30] + "..." if len(DATABASE_URL) > 30 else DATABASE_URL
        return {"db": "✅ متصل", "url_preview": safe_url, "test": str(result)}
    except Exception as e:
        from config import DATABASE_URL
        safe_url = DATABASE_URL[:30] + "..." if len(DATABASE_URL) > 30 else DATABASE_URL
        return {"db": "❌ فاشل", "error": str(e), "url_preview": safe_url}

# ── Yalidine Backup Routes (fallback) ─────────────────────
@app.get("/verify_yali_2026")
async def yali_verify(request: Request):
    crc = request.query_params.get("crc_token", "")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(crc)

@app.get("/check")
async def yalidine_check(request: Request):
    crc = request.query_params.get("crc_token", "")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(crc)

# ══════════════════════════════════════════════════════════
# Scheduler
# ══════════════════════════════════════════════════════════
from scheduler import start_scheduler

@app.on_event("startup")
async def startup_event():
    start_scheduler()
    print("🚀 Akdili شغال!")

@app.on_event("shutdown")
async def shutdown_event():
    from scheduler import stop_scheduler
    stop_scheduler()

# ══════════════════════════════════════════════════════════
# Keep-alive ping (Render free tier)
# ══════════════════════════════════════════════════════════
def _keep_alive():
    url = os.getenv("APP_URL", "https://akdilii.onrender.com") + "/health"
    while True:
        time.sleep(840)  # كل 14 دقيقة
        try:
            requests.get(url, timeout=10)
            print("💓 Keep-alive ping")
        except Exception:
            pass

threading.Thread(target=_keep_alive, daemon=True).start()

# ══════════════════════════════════════════════════════════
# تشغيل مباشر
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
