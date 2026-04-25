from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import Merchant, Carrier, Parcel, TrackingEvent, Notification
from carriers.all_carriers import get_carrier, CARRIER_CLASSES
from routes.auth import get_current_merchant
from config import CARRIERS, PLANS
from notifications import notify_customer

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
# ==========================================
# إنشاء طرد جديد في Yalidine
# ==========================================
@router.get("/parcels/create", response_class=HTMLResponse)
async def create_parcel_page(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    # جلب شركة Yalidine المربوطة
    yalidine_carrier = db.query(Carrier).filter(
        Carrier.merchant_id == merchant.id,
        Carrier.carrier_code == "yalidine",
        Carrier.is_connected == True
    ).first()

    if not yalidine_carrier:
        return RedirectResponse("/carriers?msg=connect_yalidine", status_code=302)

    # جلب الولايات من Yalidine
    from carriers.yalidine import YalidineCarrier
    yc = YalidineCarrier(
        api_key=yalidine_carrier.api_key or "",
        api_id=getattr(yalidine_carrier, "api_id", "") or ""
    )
    wilayas = yc.get_wilayas()

    return templates.TemplateResponse("create_parcel.html", {
        "request":  request,
        "merchant": merchant,
        "wilayas":  wilayas,
    })


@router.get("/parcels/communes")
async def get_communes_api(
    wilaya_id: int,
    db:        Session  = Depends(get_db),
    merchant:  Merchant = Depends(get_current_merchant)
):
    """جلب بلديات ولاية معينة (AJAX)"""
    yalidine_carrier = db.query(Carrier).filter(
        Carrier.merchant_id == merchant.id,
        Carrier.carrier_code == "yalidine",
        Carrier.is_connected == True
    ).first()
    if not yalidine_carrier:
        return JSONResponse([])

    from carriers.yalidine import YalidineCarrier
    yc = YalidineCarrier(
        api_key=yalidine_carrier.api_key or "",
        api_id=getattr(yalidine_carrier, "api_id", "") or ""
    )
    communes = yc.get_communes(wilaya_id=wilaya_id)
    return JSONResponse(communes)


@router.post("/parcels/create")
async def create_parcel_submit(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "بيانات غير صالحة"})

    # تحقق من الحقول الإلزامية
    required = ["firstname", "familyname", "contact_phone", "to_wilaya_name", "product_list", "price"]
    for f in required:
        if not body.get(f):
            return JSONResponse({"ok": False, "msg": f"الحقل '{f}' مطلوب"})

    # تحقق من حد الباقة
    from config import PLANS
    plan_info = PLANS.get(merchant.plan, PLANS["free"])
    current_count = db.query(Parcel).filter(Parcel.merchant_id == merchant.id).count()
    if current_count >= plan_info["orders"]:
        if merchant.plan == "free":
            return JSONResponse({"ok": False, "msg": "⚠️ وصلت لحد الباقة المجانية (30 طرد)"})
        return JSONResponse({"ok": False, "msg": f"⚠️ وصلت لحد باقتك ({plan_info['orders']} طرد)"})

    # جلب Yalidine carrier
    yalidine_carrier = db.query(Carrier).filter(
        Carrier.merchant_id == merchant.id,
        Carrier.carrier_code == "yalidine",
        Carrier.is_connected == True
    ).first()
    if not yalidine_carrier:
        return JSONResponse({"ok": False, "msg": "اربط حساب Yalidine أولاً"})

    from carriers.yalidine import YalidineCarrier
    import time, random
    yc = YalidineCarrier(
        api_key=yalidine_carrier.api_key or "",
        api_id=getattr(yalidine_carrier, "api_id", "") or ""
    )

    # توليد order_id تلقائي إذا ما أعطاه
    order_id = body.get("order_id") or f"AKD-{int(time.time())}-{random.randint(100,999)}"
    body["order_id"] = order_id

    # إرسال لـ Yalidine
    result = yc.create_parcel(body)

    if not result["success"]:
        return JSONResponse({"ok": False, "msg": f"❌ Yalidine: {result.get('error', 'خطأ غير معروف')}"})

    tracking = result.get("tracking", "")
    if not tracking:
        return JSONResponse({"ok": False, "msg": "❌ ما رجعلنا رقم التتبع من Yalidine"})

    # حفظ الطرد في قاعدة البيانات مع رقم الهاتف الحقيقي
    phone = body.get("contact_phone", "")
    name = (body.get("firstname", "") + " " + body.get("familyname", "")).strip()
    is_stopdesk = bool(body.get("is_stopdesk", False))

    new_parcel = Parcel(
        merchant_id     = merchant.id,
        carrier_id      = yalidine_carrier.id,
        tracking_number = str(tracking),
        customer_name   = name,
        customer_phone  = phone,
        wilaya          = body.get("to_wilaya_name", ""),
        delivery_type   = "office" if is_stopdesk else "home",
        current_status  = "at_origin",
        is_active       = True,
    )
    db.add(new_parcel)
    db.commit()
    db.refresh(new_parcel)

    # إرسال واتساب فوري لتأكيد الطرد
    try:
        from notifications import notify_customer
        notify_customer(
            phone           = phone,
            tracking_number = str(tracking),
            status          = "at_origin",
            delivery_type   = "office" if is_stopdesk else "home",
            merchant_name   = merchant.name or ""
        )
    except Exception as notif_err:
        print(f"⚠️ واتساب (غير حرج): {notif_err}")

    return JSONResponse({
        "ok": True, 
        "msg": f"✅ تم إنشاء الطرد بنجاح!",
        "tracking": tracking,
        "order_id": order_id
    })



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
@router.post("/parcels/update-phone")
async def update_phone(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    body = await request.json()
    parcel = db.query(Parcel).filter(
        Parcel.id == body.get("parcel_id"),
        Parcel.merchant_id == merchant.id
    ).first()
    if parcel:
        parcel.customer_phone = body.get("phone", "")
        db.commit()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False})

@router.post("/parcels/delete")
async def delete_parcel(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    body = await request.json()
    parcel_id = body.get("parcel_id")
    parcel = db.query(Parcel).filter(
        Parcel.id == parcel_id,
        Parcel.merchant_id == merchant.id
    ).first()
    if parcel:
        db.delete(parcel)
        db.commit()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "msg": "الطرد ما لقيناهش"})


# ==========================================
# مزامنة الطرود من شركة التوصيل
# ==========================================
def map_yalidine_status(status: str) -> str:
    mapping = {
        "1": "at_origin", "2": "in_transit", "3": "at_destination",
        "4": "out_for_delivery", "5": "delivered", "6": "failed_attempt",
        "7": "returned",
        "En préparation":        "at_origin",
        "Collecté":              "at_origin",
        "En transit":            "in_transit",
        "Arrivé wilaya":         "at_destination",
        "En cours de livraison": "out_for_delivery",
        "Livré":                 "delivered",
        "Tentative échouée":     "failed_attempt",
        "Retourné":              "returned",
        # status عام
        "at_origin":         "at_origin",
        "in_transit":        "in_transit",
        "at_destination":    "at_destination",
        "out_for_delivery":  "out_for_delivery",
        "delivered":         "delivered",
        "failed_attempt":    "failed_attempt",
        "returned":          "returned",
        # Maystro
        "TO_PREPARE":  "at_origin",
        "TO_SHIP":     "in_transit",
        "SHIPPED":     "in_transit",
        "AT_HUB":      "at_destination",
        "TO_DELIVER":  "out_for_delivery",
        "DELIVERED":   "delivered",
        "FAILED":      "failed_attempt",
        "RETURNED":    "returned",
        # ZR Express / Ecotrack / Procolis / Guepex
        "pending":     "at_origin",
        "new":         "at_origin",
        "picked_up":   "at_origin",
        "preparing":   "at_origin",
        "created":     "at_origin",
        "transit":     "in_transit",
        "in_transit":  "in_transit",
        "hub":         "at_destination",
        "arrived":     "at_destination",
        "delivering":  "out_for_delivery",
        "delivery":    "out_for_delivery",
        "out_for_delivery": "out_for_delivery",
        "livré":       "delivered",
        "undelivered": "failed_attempt",
        "failed":      "failed_attempt",
        "echec":       "failed_attempt",
        "retourné":    "returned",
    }
    return mapping.get(str(status), mapping.get(str(status).lower(), "in_transit"))


def extract_parcel_data(p: dict, carrier_code: str) -> dict:
    """استخراج بيانات الطرد من أي شركة توصيل"""

    # ---- رقم التتبع ----
    tracking_fields = {
        "yalidine":      ["tracking"],
        "zr_express":    ["tracking", "barcode", "tracking_number", "id"],
        "ecotrack":      ["tracking_code", "tracking", "barcode", "id"],
        "procolis":      ["tracking", "barcode", "numero", "id"],
        "maystro":       ["tracking", "barcode", "id"],
        "guepex":        ["tracking", "barcode", "id"],
        "ecom_delivery": ["tracking", "barcode", "numero_suivi", "id"],
    }
    tracking = ""
    for f in tracking_fields.get(carrier_code, ["tracking","id"]):
        tracking = str(p.get(f, "") or "")
        if tracking and tracking != "None": break

    # ---- الاسم ----
    if carrier_code == "yalidine":
        name = (p.get("firstname","") + " " + p.get("familyname","")).strip()
    else:
        for f in ["customer_name","recipient_name","client_name","name","nom","fullname","nom_prenom"]:
            name = str(p.get(f,"") or "")
            if name and name != "None": break
        else: name = ""

    # ---- الهاتف ----
    phone_fields = {
        "yalidine":      ["contact_phone"],
        "zr_express":    ["phone","contact_phone","client_phone","telephone"],
        "ecotrack":      ["phone","recipient_phone","contact_phone","client_phone"],
        "procolis":      ["phone","client_phone","contact_phone","telephone"],
        "maystro":       ["customer_phone","phone","contact_phone"],
        "guepex":        ["phone","contact_phone","client_phone"],
        "ecom_delivery": ["phone","telephone","contact_phone","client_phone"],
    }
    phone = ""
    for f in phone_fields.get(carrier_code, ["phone","contact_phone"]):
        phone = str(p.get(f,"") or "")
        if phone and phone != "None" and "*" not in phone: break

    # ---- الحالة ----
    status_fields = {
        "yalidine":      ["last_status","status"],
        "zr_express":    ["status","etat","last_status"],
        "ecotrack":      ["status","etat","last_status"],
        "procolis":      ["status","etat"],
        "maystro":       ["status","etat","state"],
        "guepex":        ["status","etat","last_status"],
        "ecom_delivery": ["status","etat","statut"],
    }
    raw_status = ""
    for f in status_fields.get(carrier_code, ["status","last_status"]):
        raw_status = str(p.get(f,"") or "")
        if raw_status and raw_status != "None": break

    # ---- الولاية ----
    wilaya = str(
        p.get("to_wilaya_name") or p.get("wilaya") or
        p.get("to_wilaya_id") or p.get("destination_wilaya") or ""
    )

    is_stopdesk = bool(p.get("is_stopdesk") or p.get("stopdesk") or False)

    return {
        "tracking":    tracking,
        "name":        name or "—",
        "phone":       phone or "—",
        "raw_status":  raw_status,
        "status":      map_yalidine_status(raw_status),
        "wilaya":      wilaya,
        "is_stopdesk": is_stopdesk,
    }

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
                # أضف الطرد — استخدم extract_parcel_data لكل الشركات
                extracted = extract_parcel_data(p, carrier_db.carrier_code)
                tracking  = extracted["tracking"]
                if not tracking:
                    continue
                if db.query(Parcel).filter(Parcel.tracking_number == tracking).first():
                    continue
                name       = extracted["name"]
                phone      = extracted["phone"]
                wilaya_val = extracted["wilaya"]
                status_val = extracted["status"]
                dtype      = "office" if extracted["is_stopdesk"] else "home"
                is_done    = status_val in ["delivered", "returned"]

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
                db.flush()

                # رسالة واتساب فورية عند أول مزامنة
                if phone and phone != "—" and not is_done:
                    try:
                        from notifications import notify_customer
                        result = notify_customer(
                            phone           = phone,
                            tracking_number = str(tracking),
                            status          = status_val,
                            delivery_type   = dtype,
                            merchant_name   = merchant.name or ""
                        )
                        print(f"📱 واتساب للطرد {tracking} | phone={phone} | status={status_val} | result={result}")
                    except Exception as notif_err:
                        print(f"❌ خطأ واتساب: {notif_err}")

                total_added += 1

            db.commit()

        except Exception as e:
            db.rollback()
            import traceback
            err_detail = traceback.format_exc()[-300:]
            return JSONResponse({"ok": False, "msg": f"خطأ: {str(e)} | {err_detail}"})

    return JSONResponse({"ok": True, "msg": f"✅ تمت المزامنة — {total_added} طرد جديد"})

# ==========================================
# تشغيل التتبع يدوياً الآن
# ==========================================
@router.post("/parcels/track-now")
async def track_now(
    request:  Request,
    db:       Session  = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant)
):
    """يشغل التتبع الآن لكل طرود هذا التاجر"""
    from carriers.all_carriers import get_carrier
    from models import TrackingEvent, Notification
    from notifications import notify_customer

    active_parcels = db.query(Parcel).filter(
        Parcel.merchant_id == merchant.id,
        Parcel.is_active   == True,
        ~Parcel.current_status.in_(["delivered","returned"])
    ).all()

    if not active_parcels:
        return JSONResponse({"ok": True, "msg": "ما فيه طرود نشطة للتتبع"})

    updated = 0
    notified = 0
    skipped  = 0
    errors   = []

    for parcel in active_parcels:
        try:
            carrier_db = db.query(Carrier).filter(
                Carrier.id == parcel.carrier_id,
                Carrier.is_connected == True
            ).first()
            if not carrier_db:
                skipped += 1
                continue

            carrier = get_carrier(
                carrier_code = carrier_db.carrier_code,
                api_key      = carrier_db.api_key or "",
                api_id       = getattr(carrier_db, "api_id", "") or ""
            )
            result = carrier.track_parcel(parcel.tracking_number)
            if not result:
                skipped += 1
                continue

            new_status = result.get("status","")
            location   = result.get("location","")
            if not new_status:
                skipped += 1
                continue

            already = db.query(Notification).filter(
                Notification.parcel_id == parcel.id
            ).first()

            if new_status != parcel.current_status or not already:
                event = TrackingEvent(
                    parcel_id   = parcel.id,
                    status      = new_status,
                    location    = location,
                    description = f"تتبع يدوي: {new_status}"
                )
                db.add(event)

                # واتساب فقط إذا فيه رقم حقيقي
                phone = (parcel.customer_phone or "").strip()
                if phone and "*" not in phone and len(phone) >= 9:
                    nr = notify_customer(
                        phone           = phone,
                        tracking_number = parcel.tracking_number,
                        status          = new_status,
                        delivery_type   = parcel.delivery_type or "home",
                        merchant_name   = merchant.name or ""
                    )
                    if nr.get("whatsapp_sent"):
                        db.add(Notification(
                            parcel_id=parcel.id, channel="whatsapp",
                            phone=phone, message=f"إشعار {new_status}", status="sent"
                        ))
                        notified += 1

                parcel.current_status = new_status
                parcel.wilaya         = location
                if new_status in ["delivered","returned"]:
                    parcel.is_active = False
                updated += 1
                db.commit()

        except Exception as e:
            errors.append(str(e)[:80])
            db.rollback()
            continue

    msg = f"✅ تم التتبع — {updated} طرد تحدّث | {notified} واتساب أُرسل | {skipped} تخطى"
    if errors:
        msg += f" | ❌ {len(errors)} خطأ"
    return JSONResponse({"ok": True, "msg": msg, "updated": updated, "notified": notified})
