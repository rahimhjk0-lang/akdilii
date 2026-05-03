"""
Webhook Handler — اكدلي
========================
POST /webhook/yalidine/{merchant_id}
- طرد جديد → استيراد تلقائي
- طرد موجود → تحديث حالة + واتساب
"""

import hmac, hashlib, logging
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from carriers.yalidine import YalidineCarrier
from services.magic_sync import _update_parcel_and_notify
from notifications import notify_customer

logger = logging.getLogger("akdili-webhook")
router = APIRouter(prefix="/webhook", tags=["webhook"])


# ============================================================
# POST /webhook/yalidine/{merchant_id}
# ============================================================
@router.post("/yalidine/{merchant_id}")
async def yalidine_webhook(merchant_id: int, request: Request):
    """
    Universal Webhook Handler:
    - طرد جديد  → يُنشئه في الـ DB
    - طرد موجود → يحدث الحالة + واتساب
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info(f"📥 Webhook merchant={merchant_id} | payload keys={list(payload.keys())}")

    db = SessionLocal()
    try:
        # ── جيب الشركة المربوطة لهذا التاجر ──
        carrier_db = db.query(Carrier).filter(
            Carrier.merchant_id  == merchant_id,
            Carrier.carrier_code == "yalidine",
            Carrier.is_connected == True
        ).first()

        if not carrier_db:
            logger.warning(f"⚠️ Webhook: لا شركة Yalidine مربوطة للتاجر {merchant_id}")
            return JSONResponse({"ok": False, "reason": "carrier not connected"})

        carrier_obj = YalidineCarrier(
            api_key=carrier_db.api_key or "",
            api_id=getattr(carrier_db, "api_id", "") or ""
        )

        # ── استخرج بيانات الطرد من الـ payload ──
        parcel_data = _extract_webhook_parcel(payload)
        if not parcel_data:
            return JSONResponse({"ok": False, "reason": "no parcel data"})

        tracking    = parcel_data["tracking"]
        raw_status  = parcel_data["raw_status"]
        new_status  = carrier_obj.normalize_status(raw_status)
        location    = parcel_data.get("location", "")

        logger.info(f"📦 Webhook: {tracking} | raw={raw_status} | normalized={new_status}")

        # ── هل الطرد موجود؟ ──
        existing = db.query(Parcel).filter(
            Parcel.tracking_number == tracking
        ).first()

        if existing:
            # ── طرد موجود → تحديث ──
            if new_status and new_status != existing.current_status:
                _update_parcel_and_notify(db, existing, new_status, location, source="webhook")
                db.commit()
                return JSONResponse({"ok": True, "action": "updated", "tracking": tracking})
            else:
                return JSONResponse({"ok": True, "action": "no_change", "tracking": tracking})

        else:
            # ── طرد جديد → استيراد تلقائي ──
            merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
            if not merchant:
                return JSONResponse({"ok": False, "reason": "merchant not found"})

            status_final = new_status or "at_origin"

            new_parcel = Parcel(
                merchant_id     = merchant_id,
                carrier_id      = carrier_db.id,
                tracking_number = tracking,
                customer_name   = parcel_data.get("customer_name", "زبون جديد"),
                customer_phone  = parcel_data.get("customer_phone", "0000000000"),
                wilaya          = location,
                delivery_type   = parcel_data.get("delivery_type", "home"),
                current_status  = status_final,
                is_active       = status_final not in {"delivered", "returned"},
            )
            db.add(new_parcel)
            db.flush()

            # TrackingEvent أول
            event = TrackingEvent(
                parcel_id   = new_parcel.id,
                status      = status_final,
                location    = location,
                description = f"[webhook] استيراد تلقائي — {raw_status}"
            )
            db.add(event)

            # إشعار واتساب إذا الحالة تستاهل
            if new_parcel.customer_phone != "0000000000":
                notif_result = notify_customer(
                    phone           = new_parcel.customer_phone,
                    tracking_number = tracking,
                    status          = status_final,
                    delivery_type   = new_parcel.delivery_type,
                    merchant_name   = merchant.name
                )
                if notif_result.get("whatsapp_sent"):
                    notif = Notification(
                        parcel_id = new_parcel.id,
                        channel   = "whatsapp",
                        phone     = new_parcel.customer_phone,
                        message   = f"[webhook-new] إشعار {status_final}",
                        status    = "sent"
                    )
                    db.add(notif)
                    event.whatsapp_sent = True

            db.commit()
            logger.info(f"✅ Webhook: طرد جديد {tracking} مستورد")
            return JSONResponse({"ok": True, "action": "created", "tracking": tracking})

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Webhook error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        db.close()


# ============================================================
# Helper — استخرج بيانات الطرد من payload Yalidine
# ============================================================
def _extract_webhook_parcel(payload: dict) -> dict | None:
    """
    Yalidine يبعث payload بأشكال مختلفة — نعالج كلها.
    """
    # شكل 1: {"parcel": {...}}
    data = payload.get("parcel") or payload.get("data") or payload

    tracking = (
        data.get("tracking")
        or data.get("id")
        or data.get("tracking_number")
        or data.get("barcode")
        or ""
    )
    if not tracking:
        return None

    raw_status = (
        data.get("last_status")
        or data.get("status")
        or data.get("state")
        or ""
    )

    firstname  = data.get("firstname", "") or data.get("first_name", "")
    familyname = data.get("familyname", "") or data.get("last_name", "")
    customer_name  = f"{firstname} {familyname}".strip() or "زبون"
    customer_phone = (
        data.get("contact_phone")
        or data.get("phone")
        or data.get("receiver_phone")
        or "0000000000"
    )
    location = (
        data.get("to_wilaya_name")
        or data.get("last_update_wilaya")
        or data.get("wilaya")
        or ""
    )
    delivery_type = "home" if data.get("product_list") or data.get("delivery_type") == "home" else "office"

    return {
        "tracking":      str(tracking),
        "raw_status":    raw_status,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "location":      location,
        "delivery_type": delivery_type,
    }


# ============================================================
# GET /webhook/yalidine/test — اختبار أن الـ endpoint شغال
# ============================================================
@router.get("/yalidine/test")
async def webhook_test():
    return {"status": "ok", "message": "Akdili Webhook endpoint is live ✅"}
