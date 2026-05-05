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
            from urllib.parse import parse_qs, unquote
            qs     = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            params = parse_qs(qs)

            crc_list = params.get("crc_token", [])
            crc      = unquote(crc_list[0]) if crc_list else ""

            if crc:
                print(f"[CRC] crc_token={repr(crc)}")
                # Yalidine docs: echo crc_token as plain text directly
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
