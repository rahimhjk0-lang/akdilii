import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from database import init_db
from scheduler import start_scheduler, stop_scheduler
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
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

# routes
app.include_router(auth_router)
app.include_router(dashboard_router)

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
# تشغيل مباشر — مهم لـ Render!
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
