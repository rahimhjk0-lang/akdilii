"""
Webhook Handler — اكدلي
========================
GET  /webhook/yalidine/{merchant_id}  ← Validation (Yalidine يتحقق من الرابط)
POST /webhook/yalidine/{merchant_id}  ← إشعارات حقيقية
"""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from carriers.yalidine import YalidineCarrier
from services.magic_sync import _update_parcel_and_notify
from notifications import notify_customer

logger = logging.getLogger("akdili-webhook")
router = APIRouter(prefix="/webhook", tags=["webhook"])


# ============================================================
# GET /webhook/yalidine/{merchant_id}
# Yalidine يطلب GET للتحقق من الرابط — يجب أن يرجع 200 فوراً
# ============================================================
@router.get("/yalidine/{merchant_id}")
async def yalidine_webhook_validate(merchant_id: int, request: Request):
    """Validation endpoint — يرجع 200 فوراً بدون أي شرط"""
    logger.info(f"[WEBHOOK] Yalidine validation ping — merchant={merchant_id}")
    return JSONResponse({"status": "ok", "merchant": merchant_id}, status_code=200)


# ============================================================
# POST /webhook/yalidine/{merchant_id}
# إشعارات حقيقية من Yalidine
# ============================================================
@router.post("/yalidine/{merchant_id}")
async def yalidine_webhook(merchant_id: int, request: Request):
    """
    Universal Webhook Handler — Public (لا يحتاج login):
    - طرد جديد  → يُنشئه في الـ DB
    - طرد موجود → يحدث الحالة + واتساب
    """
    # ── قراءة الـ payload بأمان — لا خطأ 400 حتى لو فارغ ──
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if not payload:
        # Yalidine أحياناً يبعث POST فارغ للتحقق → رد 200 فوراً
        return JSONResponse({"status": "ok"}, status_code=200)

    logger.info(f"[WEBHOOK] POST merchant={merchant_id} | keys={list(payload.keys())}")

    db = SessionLocal()
    try:
        carrier_db = db.query(Carrier).filter(
            Carrier.merchant_id  == merchant_id,
            Carrier.carrier_code == "yalidine",
            Carrier.is_connected == True
        ).first()

        if not carrier_db:
            logger.warning(f"[WEBHOOK] لا شركة Yalidine مربوطة للتاجر {merchant_id}")
            return JSONResponse({"ok": False, "reason": "carrier not connected"}, status_code=200)

        carrier_obj = YalidineCarrier(
            api_key=carrier_db.api_key or "",
            api_id=getattr(carrier_db, "api_id", "") or ""
        )

        parcel_data = _extract_webhook_parcel(payload)
        if not parcel_data:
            return JSONResponse({"ok": True, "reason": "no parcel data"}, status_code=200)

        tracking   = parcel_data["tracking"]
        raw_status = parcel_data["raw_status"]
        new_status = carrier_obj.normalize_status(raw_status)
        location   = parcel_data.get("location", "")

        logger.info(f"[WEBHOOK] {tracking} | raw={raw_status} | normalized={new_status}")

        existing = db.query(Parcel).filter(
            Parcel.tracking_number == tracking
        ).first()

        if existing:
            if new_status and new_status != existing.current_status:
                _update_parcel_and_notify(db, existing, new_status, location, source="webhook")
                db.commit()
                return JSONResponse({"ok": True, "action": "updated", "tracking": tracking})
            return JSONResponse({"ok": True, "action": "no_change", "tracking": tracking})

        else:
            merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
            if not merchant:
                return JSONResponse({"ok": False, "reason": "merchant not found"}, status_code=200)

            status_final = new_status or "at_origin"
            new_parcel   = Parcel(
                merchant_id     = merchant_id,
                carrier_id      = carrier_db.id,
                tracking_number = tracking,
                customer_name   = parcel_data.get("customer_name", "زبون"),
                customer_phone  = parcel_data.get("customer_phone", "0000000000"),
                wilaya          = location,
                delivery_type   = parcel_data.get("delivery_type", "home"),
                current_status  = status_final,
                is_active       = status_final not in {"delivered", "returned"},
            )
            db.add(new_parcel)
            db.flush()

            event = TrackingEvent(
                parcel_id   = new_parcel.id,
                status      = status_final,
                location    = location,
                description = f"[webhook] استيراد تلقائي — {raw_status}"
            )
            db.add(event)

            if new_parcel.customer_phone != "0000000000":
                notif_result = notify_customer(
                    phone           = new_parcel.customer_phone,
                    tracking_number = tracking,
                    status          = status_final,
                    delivery_type   = new_parcel.delivery_type,
                    merchant_name   = merchant.name
                )
                if notif_result.get("whatsapp_sent"):
                    db.add(Notification(
                        parcel_id = new_parcel.id,
                        channel   = "whatsapp",
                        phone     = new_parcel.customer_phone,
                        message   = f"[webhook-new] إشعار {status_final}",
                        status    = "sent"
                    ))
                    event.whatsapp_sent = True

            db.commit()
            logger.info(f"[WEBHOOK] ✅ طرد جديد مستورد: {tracking}")
            return JSONResponse({"ok": True, "action": "created", "tracking": tracking})

    except Exception as e:
        db.rollback()
        logger.error(f"[WEBHOOK] ❌ خطأ: {e}")
        # نرجع 200 دائماً — Yalidine ما يعيدش المحاولة على 500
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)
    finally:
        db.close()


# ============================================================
# Helper — استخرج بيانات الطرد من payload Yalidine
# ============================================================
def _extract_webhook_parcel(payload: dict) -> dict | None:
    data = payload.get("parcel") or payload.get("data") or payload

    tracking = (
        data.get("tracking") or data.get("id") or
        data.get("tracking_number") or data.get("barcode") or ""
    )
    if not tracking:
        return None

    raw_status = (
        data.get("last_status") or data.get("status") or
        data.get("state") or ""
    )
    firstname      = data.get("firstname", "") or data.get("first_name", "")
    familyname     = data.get("familyname", "") or data.get("last_name", "")
    customer_name  = f"{firstname} {familyname}".strip() or "زبون"
    customer_phone = (
        data.get("contact_phone") or data.get("phone") or
        data.get("receiver_phone") or "0000000000"
    )
    location      = (
        data.get("to_wilaya_name") or data.get("last_update_wilaya") or
        data.get("wilaya") or ""
    )
    delivery_type = "home" if data.get("product_list") or data.get("delivery_type") == "home" else "office"

    return {
        "tracking":       str(tracking),
        "raw_status":     raw_status,
        "customer_name":  customer_name,
        "customer_phone": customer_phone,
        "location":       location,
        "delivery_type":  delivery_type,
    }
