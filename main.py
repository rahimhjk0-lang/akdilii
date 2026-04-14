from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from database import init_db
from scheduler import start_scheduler, stop_scheduler
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router

# ==========================================
# تشغيل وإيقاف التطبيق
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # عند البداية
    init_db()
    start_scheduler()
    print("🚀 Akdili — اكدلي شغال!")
    yield
    # عند الإيقاف
    stop_scheduler()
    print("⏹ Akdili وقف")

# ==========================================
# إنشاء التطبيق
# ==========================================
app = FastAPI(
    title       = "Akdili — اكدلي",
    description = "منصة تتبع الطرود والإشعارات التلقائية للتجار الجزائريين",
    version     = "1.0.0",
    lifespan    = lifespan
)

# ---- الملفات الثابتة ----
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---- المسارات ----
app.include_router(auth_router)
app.include_router(dashboard_router)

# ---- الصفحة الرئيسية ----
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    token = request.cookies.get("akdili_token")
    if token:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/health")
async def health():
    return {"status": "✅ Akdili شغال", "version": "1.0.0"}
