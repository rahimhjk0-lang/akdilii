import os
import uvicorn
import requests
import threading
import time
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from database import init_db, get_db
from sqlalchemy.orm import Session
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

@app.get("/check-env")
async def check_env():
    import os
    key = os.getenv("CHARGILY_API_KEY", "")
    green_instance = os.getenv("GREEN_API_INSTANCE", "")
    green_token = os.getenv("GREEN_API_TOKEN", "")
    return {
        "has_key": bool(key),
        "key_preview": key[:10] + "..." if key else "EMPTY",
        "app_url": os.getenv("APP_URL", "not set"),
        "green_instance": repr(green_instance),
        "green_token_len": len(green_token),
        "green_token_has_newline": "\n" in green_token,
        "green_token_preview": repr(green_token[:20])
    }

@app.get("/debug-yalidine")
async def debug_yalidine(db: Session = Depends(get_db)):
    from models import Carrier
    from carriers.all_carriers import get_carrier
    carrier_db = db.query(Carrier).filter(Carrier.carrier_code == "yalidine", Carrier.is_connected == True).first()
    if not carrier_db:
        return {"error": "ما فيه Yalidine مربوط"}
    carrier = get_carrier("yalidine", api_key=carrier_db.api_key or "", api_id=getattr(carrier_db, "api_id", "") or "")
    parcels = carrier.get_parcels()
    if not parcels:
        return {"error": "ما رجع بيانات", "count": 0}
    # أرجع أول طرد كاملاً
    return {"first_parcel_keys": list(parcels[0].keys()), "first_parcel": parcels[0], "total": len(parcels)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

@app.get("/debug-communes")
async def debug_communes(wilaya_id: int = 1, db: Session = Depends(get_db)):
    from models import Carrier
    from carriers.yalidine import YalidineCarrier
    carrier_db = db.query(Carrier).filter(Carrier.carrier_code == "yalidine", Carrier.is_connected == True).first()
    if not carrier_db:
        return {"error": "ما فيه Yalidine مربوط"}
    yc = YalidineCarrier(api_key=carrier_db.api_key or "", api_id=getattr(carrier_db, "api_id", "") or "")
    communes = yc.get_communes(wilaya_id=wilaya_id)
    if not communes:
        return {"error": "ما رجع بيانات", "count": 0}
    return {"count": len(communes), "first_3": communes[:3], "keys": list(communes[0].keys()) if communes else []}

@app.get("/debug-wilayas")
async def debug_wilayas(db: Session = Depends(get_db)):
    from models import Carrier
    from carriers.yalidine import YalidineCarrier
    carrier_db = db.query(Carrier).filter(Carrier.carrier_code == "yalidine", Carrier.is_connected == True).first()
    if not carrier_db:
        return {"error": "ما فيه Yalidine مربوط"}
    yc = YalidineCarrier(api_key=carrier_db.api_key or "", api_id=getattr(carrier_db, "api_id", "") or "")
    wilayas = yc.get_wilayas()
    if not wilayas:
        return {"error": "ما رجع بيانات"}
    return {"count": len(wilayas), "first_3": wilayas[:3], "keys": list(wilayas[0].keys()) if wilayas else []}

@app.post("/debug-create-parcel")
async def debug_create_parcel(db: Session = Depends(get_db)):
    """تست إنشاء طرد مباشرة في Yalidine بدون auth"""
    from models import Carrier
    from carriers.yalidine import YalidineCarrier
    import time, random

    carrier_db = db.query(Carrier).filter(
        Carrier.carrier_code == "yalidine",
        Carrier.is_connected == True
    ).first()
    if not carrier_db:
        return {"error": "ما فيه Yalidine مربوط"}

    yc = YalidineCarrier(
        api_key=carrier_db.api_key or "",
        api_id=getattr(carrier_db, "api_id", "") or ""
    )

    test_data = {
        "order_id":        f"TEST-{int(time.time())}",
        "firstname":       "تست",
        "familyname":      "اكدلي",
        "contact_phone":   "0555000000",
        "address":         "تست",
        "to_wilaya_name":  "Alger",
        "to_commune_name": "Alger Centre",
        "product_list":    "منتج تجريبي",
        "price":           1000,
        "is_stopdesk":     False,
        "freeshipping":    False,
    }

    result = yc.create_parcel(test_data)
    return {
        "api_id_set": bool(carrier_db.api_id),
        "api_key_len": len(carrier_db.api_key or ""),
        "payload_sent": test_data,
        "result": result
    }
