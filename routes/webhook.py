from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification
from notifications import notify_customer

router = APIRouter(prefix="/webhook")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# خريطة حالات Yalidine
STATUS_MAP = {
    "En préparation":        "at_origin",
    "Collecté":              "at_origin",
    "En transit":            "in_transit",
    "Arrivé wilaya":         "at_destination",
    "En cours de livraison": "out_for_delivery",
    "Livré":                 "delivered",
    "Tentative échouée":     "failed_attempt",
    "Retourné":              "returned",
}

@router.post("/yalidine")
async def yalidine_webhook(request: Request):
    """
    Yalidine يبعث هنا عند كل تغيير في حالة الطرد
    """
    db = SessionLocal()
    try:
        data = await request.json()
        print(f"📬 Webhook Yalidine: {data}")

        tracking = data.get("tracking") or data.get("id") or data.get("tracking_number", "")
        new_status_raw = data.get("status") or data.get("last_status", "")
        phone = data.get("contact_phone") or data.get("phone") or data.get("recipient_phone", "")
        location = data.get("current_wilaya_name") or data.get("wilaya", "")

        if not tracking or not new_status_raw:
            return JSONResponse({"ok": False, "msg": "بيانات ناقصة"})

        new_status = STATUS_MAP.get(new_status_raw, "in_transit")

        # ابحث عن الطرد في قاعدة البيانات
        parcel = db.query(Parcel).filter(
            Parcel.tracking_number == str(tracking)
        ).first()

        if not parcel:
            print(f"⚠️ طرد غير موجود: {tracking}")
            return JSONResponse({"ok": True, "msg": "طرد غير مسجل"})

        # إذا تغيرت الحالة
        if new_status != parcel.current_status:
            print(f"📦 {tracking}: {parcel.current_status} → {new_status}")

            # حفظ الحدث
            event = TrackingEvent(
                parcel_id   = parcel.id,
                status      = new_status,
                location    = location,
                description = f"webhook: {new_status_raw}"
            )
            db.add(event)

            # تحديث الطرد
            if phone and phone != "—":
                parcel.customer_phone = phone
            parcel.current_status = new_status
            if location:
                parcel.wilaya = location
            if new_status in ["delivered", "returned"]:
                parcel.is_active = False

            db.commit()

            # إرسال واتساب
            send_phone = phone or parcel.customer_phone
            if send_phone and send_phone != "—":
                merchant = parcel.merchant
                result = notify_customer(
                    phone           = send_phone,
                    tracking_number = tracking,
                    status          = new_status,
                    delivery_type   = parcel.delivery_type or "home",
                    merchant_name   = merchant.name if merchant else ""
                )
                print(f"📱 إشعار webhook: {result}")

        return JSONResponse({"ok": True})

    except Exception as e:
        db.rollback()
        print(f"❌ خطأ webhook: {e}")
        return JSONResponse({"ok": False, "msg": str(e)})
    finally:
        db.close()
