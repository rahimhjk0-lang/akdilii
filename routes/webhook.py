"""
Webhook Handler — اكدلي
========================
GET  /webhook/yalidine        ← Validation (crc_token)
GET  /webhook/yalidine/       ← نفس الشيء (trailing slash)
POST /webhook/yalidine        ← إشعارات الطرود
"""

import json as _json
import logging
from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from carriers.yalidine import YalidineCarrier
from services.magic_sync import _update_parcel_and_notify
from notifications import notify_customer

logger = logging.getLogger("akdili-webhook")

# prefix فارغ — المسارات كاملة في الـ decorator
router = APIRouter(tags=["webhook"])


# ============================================================
# Flexible route — GET + POST + trailing slash
# /webhook/yalidine  و  /webhook/yalidine/
# ============================================================
@router.api_route(
    "/webhook/yalidine",
    methods=["GET", "POST"],
    include_in_schema=True,
)
@router.api_route(
    "/webhook/yalidine/",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def yalidine_webhook_flex(request: Request):
    """Unified handler — GET=validation, POST=parcel events"""

    # ── DEBUG ──
    print(f"[WH] {request.method} | params={dict(request.query_params)}")
    print(f"[WH] Headers: {dict(request.headers)}")

    # ════════════════════════════════════════════════════════
    # GET — Validation (crc_token)
    # ════════════════════════════════════════════════════════
    if request.method == "GET":
        crc_token = ""

        # 1) URL params
        crc_token = request.query_params.get("crc_token", "").strip()

        # 2) JSON body
        if not crc_token:
            try:
                body = await request.json()
                crc_token = str(body.get("crc_token", "")).strip()
                print(f"[WH] JSON body: {body}")
            except Exception:
                pass

        # 3) Form data
        if not crc_token:
            try:
                form = await request.form()
                crc_token = str(form.get("crc_token", "")).strip()
                print(f"[WH] Form: {dict(form)}")
            except Exception:
                pass

        print(f"[WH] crc_token={repr(crc_token)}")

        if crc_token:
            return Response(
                content=_json.dumps({"crc_token": crc_token}, separators=(",", ":")),
                status_code=200,
                media_type="application/json",
            )
        return Response(
            content='{"status":"ok"}',
            status_code=200,
            media_type="application/json",
        )

    # ════════════════════════════════════════════════════════
    # POST — Parcel events
    # ════════════════════════════════════════════════════════
    try:
        payload = await request.json()
        print(f"[WH] POST body: {_json.dumps(payload)[:300]}")
    except Exception:
        payload = {}

    if not payload:
        return Response(content='{"status":"ok"}', status_code=200, media_type="application/json")

    # استخرج merchant_id من الـ payload أو الـ header
    merchant_id = (
        payload.get("merchant_id")
        or payload.get("user_id")
        or request.headers.get("X-Merchant-Id")
    )

    db = SessionLocal()
    try:
        # إذا ما فيش merchant_id → نبحث على أول carrier Yalidine
        if merchant_id:
            carrier_db = db.query(Carrier).filter(
                Carrier.merchant_id  == int(merchant_id),
                Carrier.carrier_code == "yalidine",
                Carrier.is_connected == True
            ).first()
        else:
            carrier_db = db.query(Carrier).filter(
                Carrier.carrier_code == "yalidine",
                Carrier.is_connected == True
            ).first()

        if not carrier_db:
            print("[WH] No Yalidine carrier found")
            return Response(content='{"ok":false,"reason":"no carrier"}', status_code=200, media_type="application/json")

        carrier_obj = YalidineCarrier(
            api_key=carrier_db.api_key or "",
            api_id=getattr(carrier_db, "api_id", "") or ""
        )

        parcel_data = _extract_webhook_parcel(payload)
        if not parcel_data:
            return Response(content='{"ok":true,"reason":"no parcel data"}', status_code=200, media_type="application/json")

        tracking   = parcel_data["tracking"]
        raw_status = parcel_data["raw_status"]
        new_status = carrier_obj.normalize_status(raw_status)
        location   = parcel_data.get("location", "")

        print(f"[WH] {tracking} raw={raw_status} → {new_status}")

        existing = db.query(Parcel).filter(Parcel.tracking_number == tracking).first()

        if existing:
            if new_status and new_status != existing.current_status:
                _update_parcel_and_notify(db, existing, new_status, location, source="webhook")
                db.commit()
                return Response(content=_json.dumps({"ok":True,"action":"updated","tracking":tracking}),
                                status_code=200, media_type="application/json")
            return Response(content='{"ok":true,"action":"no_change"}', status_code=200, media_type="application/json")

        # طرد جديد
        merchant = db.query(Merchant).filter(Merchant.id == carrier_db.merchant_id).first()
        status_final = new_status or "at_origin"
        new_parcel = Parcel(
            merchant_id     = carrier_db.merchant_id,
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
        db.add(TrackingEvent(
            parcel_id   = new_parcel.id,
            status      = status_final,
            location    = location,
            description = f"[webhook] {raw_status}"
        ))
        if new_parcel.customer_phone != "0000000000":
            notif = notify_customer(
                phone=new_parcel.customer_phone,
                tracking_number=tracking,
                status=status_final,
                delivery_type=new_parcel.delivery_type,
                merchant_name=merchant.name if merchant else ""
            )
            if notif.get("whatsapp_sent"):
                db.add(Notification(parcel_id=new_parcel.id, channel="whatsapp",
                    phone=new_parcel.customer_phone, message=f"[wh] {status_final}", status="sent"))
        db.commit()
        print(f"[WH] ✅ created {tracking}")
        return Response(content=_json.dumps({"ok":True,"action":"created","tracking":tracking}),
                        status_code=200, media_type="application/json")

    except Exception as e:
        db.rollback()
        print(f"[WH] ❌ {e}")
        return Response(content=_json.dumps({"ok":False,"error":str(e)}),
                        status_code=200, media_type="application/json")
    finally:
        db.close()


# ────────────────────────────────────────────────────────────
# helper
# ────────────────────────────────────────────────────────────
def _extract_webhook_parcel(payload: dict):
    data = payload.get("parcel") or payload.get("data") or payload
    tracking = (data.get("tracking") or data.get("id") or
                data.get("tracking_number") or data.get("barcode") or "")
    if not tracking:
        return None
    raw_status    = data.get("last_status") or data.get("status") or data.get("state") or ""
    firstname     = data.get("firstname", "") or data.get("first_name", "")
    familyname    = data.get("familyname", "") or data.get("last_name", "")
    customer_name = f"{firstname} {familyname}".strip() or "زبون"
    customer_phone = (data.get("contact_phone") or data.get("phone") or
                      data.get("receiver_phone") or "0000000000")
    location      = (data.get("to_wilaya_name") or data.get("last_update_wilaya") or
                     data.get("wilaya") or "")
    delivery_type = "home" if data.get("product_list") or data.get("delivery_type") == "home" else "office"
    return {"tracking": str(tracking), "raw_status": raw_status,
            "customer_name": customer_name, "customer_phone": customer_phone,
            "location": location, "delivery_type": delivery_type}
