from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import Merchant, Carrier, Parcel, TrackingEvent, Notification
from carriers.all_carriers import get_carrier, CARRIER_CLASSES
from routes.auth import get_current_merchant
from config import CARRIERS, PLANS

router    = APIRouter()
templates = Jinja2Templates(directory="templates")

# ==========================================
# لوحة التحكم الرئيسية
# ==========================================
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    # إحصائيات
    total_parcels    = db.query(Parcel).filter(Parcel.merchant_id == merchant.id).count()
    active_parcels   = db.query(Parcel).filter(Parcel.merchant_id == merchant.id, Parcel.is_active == True).count()
    delivered        = db.query(Parcel).filter(Parcel.merchant_id == merchant.id, Parcel.current_status == "delivered").count()
    failed           = db.query(Parcel).filter(Parcel.merchant_id == merchant.id, Parcel.current_status == "failed_attempt").count()
    notifs_sent      = db.query(Notification).join(Parcel).filter(Parcel.merchant_id == merchant.id).count()

    # آخر 10 طرود
    recent_parcels = db.query(Parcel).filter(
        Parcel.merchant_id == merchant.id
    ).order_by(Parcel.updated_at.desc()).limit(10).all()

    plan_info = PLANS.get(merchant.plan, PLANS["starter"])

    return templates.TemplateResponse("dashboard.html", {
        "request":        request,
        "merchant":       merchant,
        "plan":           plan_info,
        "total_parcels":  total_parcels,
        "active_parcels": active_parcels,
        "delivered":      delivered,
        "failed":         failed,
        "notifs_sent":    notifs_sent,
        "recent_parcels": recent_parcels,
        "carriers":       CARRIERS,
    })

# ==========================================
# صفحة الطرود
# ==========================================
@router.get("/parcels", response_class=HTMLResponse)
async def parcels_page(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    parcels = db.query(Parcel).filter(
        Parcel.merchant_id == merchant.id
    ).order_by(Parcel.created_at.desc()).all()

    return templates.TemplateResponse("parcels.html", {
        "request":  request,
        "merchant": merchant,
        "parcels":  parcels,
    })

# ==========================================
# ربط شركة توصيل
# ==========================================
@router.get("/carriers", response_class=HTMLResponse)
async def carriers_page(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    my_carriers = db.query(Carrier).filter(Carrier.merchant_id == merchant.id).all()
    connected   = {c.carrier_code: c for c in my_carriers}

    return templates.TemplateResponse("carriers.html", {
        "request":       request,
        "merchant":      merchant,
        "all_carriers":  CARRIERS,
        "connected":     connected,
    })

@router.post("/carriers/connect")
async def connect_carrier(
    request:      Request,
    carrier_code: str = Form(...),
    email:        str = Form(...),
    password:     str = Form(""),   # اختياري — فارغ لشركات Token فقط
    db:           Session  = Depends(get_db),
    merchant:     Merchant = Depends(get_current_merchant)
):
    # ===== شركات Token مباشر (بدون login) =====
    DIRECT_TOKEN_CARRIERS = {"zr_express", "ecotrack", "procolis", "maystro", "guepex", "ecom_delivery"}

    if carrier_code in DIRECT_TOKEN_CARRIERS:
        # email = field1 = التوكن المباشر
        api_token = email.strip()
        if not api_token:
            return JSONResponse({"success": False, "error": "⚠️ أدخل API Token"})

        existing = db.query(Carrier).filter(
            Carrier.merchant_id  == merchant.id,
            Carrier.carrier_code == carrier_code
        ).first()

        if existing:
            existing.api_key      = api_token
            existing.api_id       = ""
            existing.is_connected = True
        else:
            db.add(Carrier(
                merchant_id  = merchant.id,
                carrier_code = carrier_code,
                carrier_name = CARRIERS.get(carrier_code, {}).get("name", carrier_code),
                api_key      = api_token,
                api_id       = "",
                is_connected = True
            ))

        db.commit()
        return JSONResponse({"success": True, "message": f"✅ تم ربط {carrier_code} بنجاح!"})

    # ===== شركات API ID + Token (مثل Yalidine) =====
    carrier_cls = CARRIER_CLASSES.get(carrier_code)
    if not carrier_cls:
        return JSONResponse({"success": False, "error": "شركة غير معروفة"})

    # email = API ID  |  password = API Token
    api_id    = email.strip()
    api_token = password.strip()

    if not api_id or not api_token:
        return JSONResponse({"success": False, "error": "⚠️ أدخل API ID و API Token"})

    # اختبار الاتصال مع Yalidine
    carrier_obj = carrier_cls(api_key=api_token)
    result = carrier_obj.login_and_get_key(api_id, api_token)

    if not result.get("success"):
        return JSONResponse({"success": False, "error": result.get("error", "فشل الربط — تحقق من المفاتيح")})

    existing = db.query(Carrier).filter(
        Carrier.merchant_id  == merchant.id,
        Carrier.carrier_code == carrier_code
    ).first()

    if existing:
        existing.api_key      = api_token
        existing.api_id       = api_id
        existing.is_connected = True
    else:
        db.add(Carrier(
            merchant_id  = merchant.id,
            carrier_code = carrier_code,
            carrier_name = CARRIERS.get(carrier_code, {}).get("name", carrier_code),
            api_key      = api_token,
            api_id       = api_id,
            is_connected = True
        ))

    db.commit()
    return JSONResponse({"success": True, "message": f"✅ تم ربط {carrier_code} بنجاح!"})


@router.post("/carriers/disconnect")
async def disconnect_carrier(
    carrier_code: str = Form(...),
    db:           Session  = Depends(get_db),
    merchant:     Merchant = Depends(get_current_merchant)
):
    carrier = db.query(Carrier).filter(
        Carrier.merchant_id  == merchant.id,
        Carrier.carrier_code == carrier_code
    ).first()
    if carrier:
        carrier.is_connected = False
        carrier.api_key      = None
        carrier.api_id       = None
        db.commit()
    return JSONResponse({"success": True})

# ==========================================
# صفحة الباقات
# ==========================================
@router.get("/plans", response_class=HTMLResponse)
async def plans_page(
    request:  Request,
    merchant: Merchant = Depends(get_current_merchant)
):
    return templates.TemplateResponse("plans.html", {
        "request":  request,
        "merchant": merchant,
        "plans":    PLANS,
    })

# ==========================================
# تفاصيل طرد واحد
# ==========================================
@router.get("/parcels/{parcel_id}", response_class=HTMLResponse)
async def parcel_detail(
    request:   Request,
    parcel_id: int,
    db:        Session  = Depends(get_db),
    merchant:  Merchant = Depends(get_current_merchant)
):
    parcel = db.query(Parcel).filter(
        Parcel.id          == parcel_id,
        Parcel.merchant_id == merchant.id
    ).first()

    if not parcel:
        raise HTTPException(status_code=404, detail="الطرد ما لقيناهش")

    events = db.query(TrackingEvent).filter(
        TrackingEvent.parcel_id == parcel_id
    ).order_by(TrackingEvent.event_time.desc()).all()

    notifs = db.query(Notification).filter(
        Notification.parcel_id == parcel_id
    ).order_by(Notification.sent_at.desc()).all()

    return templates.TemplateResponse("parcel_detail.html", {
        "request":  request,
        "merchant": merchant,
        "parcel":   parcel,
        "events":   events,
        "notifs":   notifs,
    })
