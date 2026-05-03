import json as _json, logging
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from carriers.yalidine import YalidineCarrier
from services.magic_sync import _update_parcel_and_notify
from notifications import notify_customer

logger = logging.getLogger("akdili-webhook")
router = APIRouter(tags=["webhook"])


# ── GET: Yalidine validation ─────────────────────────────────
@router.get("/webhook/yalidine")
@router.get("/webhook/yalidine/", include_in_schema=False)
async def yalidine_validate(crc_token: Optional[str] = None):
    print(f"Received CRC Token: {crc_token}")
    if crc_token:
        return {"crc_token": crc_token}
    return {"status": "ok"}


# ── POST: parcel events ──────────────────────────────────────
@router.post("/webhook/yalidine")
@router.post("/webhook/yalidine/", include_in_schema=False)
async def yalidine_webhook(request: Request):
    try:
        payload = await request.json()
        print(f"[WH] POST body: {_json.dumps(payload)[:300]}")
    except Exception:
        payload = {}

    if not payload:
        return JSONResponse({"status": "ok"})

    db = SessionLocal()
    try:
        carrier_db = db.query(Carrier).filter(
            Carrier.carrier_code == "yalidine",
            Carrier.is_connected == True
        ).first()

        if not carrier_db:
            return JSONResponse({"ok": False, "reason": "no carrier"})

        carrier_obj = YalidineCarrier(
            api_key=carrier_db.api_key or "",
            api_id=getattr(carrier_db, "api_id", "") or ""
        )

        parcel_data = _extract(payload)
        if not parcel_data:
            return JSONResponse({"ok": True, "reason": "no parcel data"})

        tracking   = parcel_data["tracking"]
        new_status = carrier_obj.normalize_status(parcel_data["raw_status"])
        location   = parcel_data.get("location", "")
        print(f"[WH] {tracking} -> {new_status}")

        existing = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()

        if existing:
            if new_status and new_status != existing.current_status:
                _update_parcel_and_notify(db, existing, new_status, location, source="webhook")
                db.commit()
            return JSONResponse({"ok": True, "tracking": tracking})

        merchant = db.query(Merchant).filter(Merchant.id == carrier_db.merchant_id).first()
        sf = new_status or "at_origin"
        p  = Parcel(
            merchant_id=carrier_db.merchant_id, carrier_id=carrier_db.id,
            tracking_number=tracking,
            customer_name=parcel_data.get("customer_name", "زبون"),
            customer_phone=parcel_data.get("customer_phone", "0000000000"),
            wilaya=location, delivery_type=parcel_data.get("delivery_type", "home"),
            current_status=sf, is_active=sf not in {"delivered", "returned"},
        )
        db.add(p); db.flush()
        db.add(TrackingEvent(parcel_id=p.id, status=sf, location=location,
                             description=f"[wh] {parcel_data['raw_status']}"))
        if p.customer_phone != "0000000000":
            n = notify_customer(phone=p.customer_phone, tracking_number=tracking,
                                status=sf, delivery_type=p.delivery_type,
                                merchant_name=merchant.name if merchant else "")
            if n.get("whatsapp_sent"):
                db.add(Notification(parcel_id=p.id, channel="whatsapp",
                    phone=p.customer_phone, message=f"[wh] {sf}", status="sent"))
        db.commit()
        return JSONResponse({"ok": True, "action": "created", "tracking": tracking})

    except Exception as e:
        db.rollback()
        print(f"[WH] error: {e}")
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        db.close()


def _extract(payload):
    d = payload.get("parcel") or payload.get("data") or payload
    t = d.get("tracking") or d.get("id") or d.get("tracking_number") or d.get("barcode") or ""
    if not t:
        return None
    return {
        "tracking":       str(t),
        "raw_status":     d.get("last_status") or d.get("status") or d.get("state") or "",
        "customer_name":  ((d.get("firstname","") or "") + " " + (d.get("familyname","") or "")).strip() or "زبون",
        "customer_phone": d.get("contact_phone") or d.get("phone") or "0000000000",
        "location":       d.get("to_wilaya_name") or d.get("last_update_wilaya") or d.get("wilaya") or "",
        "delivery_type":  "home" if d.get("product_list") or d.get("delivery_type") == "home" else "office",
    }
