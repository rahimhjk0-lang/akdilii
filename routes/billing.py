import hmac
import hashlib
import json
from datetime import datetime, timedelta

import requests as http_req
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Merchant
from config import PLANS, CHARGILY_API_KEY, CHARGILY_WEBHOOK_SECRET, APP_URL
from routes.auth import get_current_merchant

router    = APIRouter(prefix="/billing")
templates = Jinja2Templates(directory="templates")

CHARGILY_API = "https://pay.chargily.net/api/v2"

# ============================================================
# تفعيل الباقة المجانية بدون دفع
# ============================================================
@router.post("/activate-free")
async def activate_free(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    if merchant.plan != "free" and merchant.plan is not None:
        return JSONResponse({"error": "أنت مشترك في باقة مدفوعة"}, status_code=400)
    merchant.plan     = "free"
    merchant.sub_plan = "free"
    merchant.is_active = True
    db.commit()
    return JSONResponse({"ok": True, "msg": "✅ تم تفعيل الباقة المجانية"})

# ============================================================
# صفحة الاشتراك
# ============================================================
@router.get("", response_class=HTMLResponse)
async def billing_page(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    return templates.TemplateResponse("billing.html", {
        "request":  request,
        "merchant": merchant,
        "plans":    PLANS,
    })


# ============================================================
# إنشاء Checkout في Chargily
# ============================================================
@router.post("/create-checkout")
async def create_checkout(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    body = await request.json()
    plan_key = body.get("plan")

    if plan_key not in PLANS:
        return JSONResponse({"error": "باقة غير موجودة"}, status_code=400)

    if not CHARGILY_API_KEY:
        return JSONResponse({"error": "⚠️ Chargily API Key غير مضبوط — تواصل مع الإدارة"}, status_code=500)

    plan = PLANS[plan_key]

    payload = {
        "amount":       plan["price"],        # بالدينار الجزائري
        "currency":     "dzd",
        "payment_method": "edahabia",          # CCP / Dahabia / CIB
        "success_url":  f"{APP_URL}/billing/success",
        "failure_url":  f"{APP_URL}/billing/failure",
        "webhook_endpoint": f"{APP_URL}/billing/webhook",
        "description":  f"اشتراك {plan['name']} — Akdili",
        "metadata": {
            "merchant_id": str(merchant.id),
            "plan_key":    plan_key,
        },
        "locale": "ar",
    }

    try:
        resp = http_req.post(
            f"{CHARGILY_API}/checkouts",
            headers={
                "Authorization": f"Bearer {CHARGILY_API_KEY}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=15
        )
        data = resp.json()
    except Exception as e:
        return JSONResponse({"error": f"خطأ في الاتصال بـ Chargily: {e}"}, status_code=500)

    if resp.status_code != 200 or "checkout_url" not in data:
        return JSONResponse({"error": data.get("message", "فشل إنشاء الدفع")}, status_code=400)

    return JSONResponse({"checkout_url": data["checkout_url"]})


# ============================================================
# Webhook — Chargily يبعث هنا بعد الدفع
# ============================================================
@router.post("/webhook")
async def chargily_webhook(request: Request, db: Session = Depends(get_db)):
    body      = await request.body()
    signature = request.headers.get("signature", "")

    # التحقق من التوقيع
    if CHARGILY_WEBHOOK_SECRET:
        expected = hmac.new(
            CHARGILY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # نتعامل فقط مع checkout.paid
    if event.get("type") != "checkout.paid":
        return {"received": True}

    checkout = event.get("data", {})
    metadata = checkout.get("metadata", {})

    merchant_id = metadata.get("merchant_id")
    plan_key    = metadata.get("plan_key")

    if not merchant_id or not plan_key:
        return {"received": True}

    merchant = db.query(Merchant).filter(Merchant.id == int(merchant_id)).first()
    if not merchant:
        return {"received": True}

    # تفعيل الاشتراك 30 يوم
    merchant.sub_active  = True
    merchant.sub_plan    = plan_key
    merchant.sub_expires = datetime.utcnow() + timedelta(days=30)
    merchant.plan        = plan_key

    db.commit()
    print(f"✅ Subscription activated: merchant {merchant_id} → {plan_key}")

    return {"received": True}


# ============================================================
# صفحات النجاح والفشل
# ============================================================
@router.get("/success", response_class=HTMLResponse)
async def payment_success(request: Request, merchant: Merchant = Depends(get_current_merchant)):
    return templates.TemplateResponse("payment_result.html", {
        "request": request,
        "merchant": merchant,
        "success": True,
    })

@router.get("/failure", response_class=HTMLResponse)
async def payment_failure(request: Request, merchant: Merchant = Depends(get_current_merchant)):
    return templates.TemplateResponse("payment_result.html", {
        "request": request,
        "merchant": merchant,
        "success": False,
    })
