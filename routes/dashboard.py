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

    # شركات التوصيل المربوطة
    carriers = db.query(Carrier).filter(
        Carrier.merchant_id == merchant.id,
        Carrier.is_connected == True
    ).all()

    return templates.TemplateResponse("parcels.html", {
        "request":  request,
        "merchant": merchant,
        "parcels":  parcels,
        "carriers": carriers,
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
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    total_parcels = db.query(Parcel).filter(Parcel.merchant_id == merchant.id).count()
    return templates.TemplateResponse("plans.html", {
        "request":      request,
        "merchant":     merchant,
        "plans":        PLANS,
        "total_parcels": total_parcels,
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


# ==========================================
# إضافة طرد جديد
# ==========================================
@router.post("/parcels/add")
async def add_parcel(
    request:        Request,
    tracking_number: str = Form(...),
    customer_name:   str = Form(...),
    customer_phone:  str = Form(...),
    carrier_id:      int = Form(...),
    delivery_type:   str = Form("home"),
    wilaya:          str = Form(""),
    db:              Session  = Depends(get_db),
    merchant:        Merchant = Depends(get_current_merchant)
):
    # تحقق إذا الطرد موجود من قبل
    existing = db.query(Parcel).filter(Parcel.tracking_number == tracking_number).first()
    if existing:
        return JSONResponse({"ok": False, "msg": "رقم التتبع موجود من قبل"})

    # تحقق من الـ carrier
    carrier = db.query(Carrier).filter(
        Carrier.id == carrier_id,
        Carrier.merchant_id == merchant.id
    ).first()
    if not carrier:
        return JSONResponse({"ok": False, "msg": "شركة التوصيل غير موجودة"})

    parcel = Parcel(
        merchant_id      = merchant.id,
        carrier_id       = carrier_id,
        tracking_number  = tracking_number,
        customer_name    = customer_name,
        customer_phone   = customer_phone,
        wilaya           = wilaya,
        delivery_type    = delivery_type,
        current_status   = "at_origin",
        is_active        = True,
    )
    db.add(parcel)
    db.commit()
    db.refresh(parcel)
    return JSONResponse({"ok": True, "msg": "✅ تم إضافة الطرد", "id": parcel.id})

# ==========================================
# حذف طرد
# ==========================================
@router.post("/parcels/delete")
async def delete_parcel(
    request:   Request,
    parcel_id: int     = Form(...),
    db:        Session = Depends(get_db),
    merchant:  Merchant = Depends(get_current_merchant)
):
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.merchant_id == merchant.id
    ).first()
    if parcel:
        db.delete(parcel)
        db.commit()
    return JSONResponse({"ok": True})


# ==========================================
# مزامنة الطرود من شركة التوصيل
# ==========================================
def map_yalidine_status(status: str) -> str:
    mapping = {
        "1": "at_origin", "2": "in_transit", "3": "at_destination",
        "4": "out_for_delivery", "5": "delivered", "6": "failed_attempt",
        "7": "returned", "Ready": "at_origin", "En route": "in_transit",
        "Arrived": "at_destination", "Out for delivery": "out_for_delivery",
        "Delivered": "delivered", "Failed": "failed_attempt", "Returned": "returned",
    }
    return mapping.get(str(status), "at_origin")

@router.post("/carriers/sync")
async def sync_parcels(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    # جلب كل الشركات المربوطة
    carriers_db = db.query(Carrier).filter(
        Carrier.merchant_id == merchant.id,
        Carrier.is_connected == True
    ).all()

    if not carriers_db:
        return JSONResponse({"ok": False, "msg": "ما فيه شركة توصيل مربوطة"})

    # فحص حد الباقة
    from config import PLANS
    plan_info = PLANS.get(merchant.plan, PLANS["free"])
    current_count = db.query(Parcel).filter(Parcel.merchant_id == merchant.id).count()
    if current_count >= plan_info["orders"]:
        if merchant.plan == "free":
            return JSONResponse({"ok": False, "msg": f"⚠️ وصلت لحد الباقة المجانية (30 طرد) — اشترك في باقة مدفوعة للاستمرار"})
        return JSONResponse({"ok": False, "msg": f"⚠️ وصلت لحد باقتك ({plan_info['orders']} طرد)"})

    total_added = 0

    for carrier_db in carriers_db:
        try:
            carrier = get_carrier(
                carrier_code = carrier_db.carrier_code,
                api_key      = carrier_db.api_key or "",
                api_id       = getattr(carrier_db, "api_id", "") or ""
            )
            parcels_data = carrier.get_parcels()

            # فلتر آخر 30 يوم فقط
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(days=30)

            for p in parcels_data:
                # تحقق من التاريخ
                date_str = p.get("date", "") or p.get("created_at", "") or p.get("last_update", "")
                if date_str:
                    try:
                        p_date = datetime.fromisoformat(date_str[:10])
                        if p_date < cutoff:
                            continue
                    except:
                        pass
                tracking = p.get("tracking", "") or p.get("id", "") or p.get("tracking_number", "")
                if not tracking:
                    continue
                # إذا موجود من قبل — تخطى
                if db.query(Parcel).filter(Parcel.tracking_number == str(tracking)).first():
                    continue
                # أضف الطرد
                # حقول Yalidine الصحيحة
                name  = (p.get("firstname", "") + " " + p.get("familyname", "")).strip() or p.get("customer_name", "") or "—"
                phone = p.get("phone", "") or p.get("customer_phone", "") or "—"
                wilaya_val = str(p.get("to_wilaya_id", "") or p.get("wilaya_id", "") or p.get("wilaya", "") or "")
                is_stopdesk = p.get("is_stopdesk", False)
                dtype = "office" if is_stopdesk else "home"
                raw_status = p.get("status", "1") or p.get("current_status", "1")
                status_val = map_yalidine_status(str(raw_status))
                is_done = status_val in ["delivered", "returned"]

                new_parcel = Parcel(
                    merchant_id     = merchant.id,
                    carrier_id      = carrier_db.id,
                    tracking_number = str(tracking),
                    customer_name   = name,
                    customer_phone  = phone,
                    wilaya          = wilaya_val,
                    delivery_type   = dtype,
                    current_status  = status_val,
                    is_active       = not is_done,
                )
                db.add(new_parcel)
                total_added += 1

            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse({"ok": False, "msg": f"خطأ: {str(e)}"})

    return JSONResponse({"ok": True, "msg": f"✅ تمت المزامنة — {total_added} طرد جديد"})
