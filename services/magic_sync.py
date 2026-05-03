"""
Magic Sync Service — اكدلي
==========================
- Initial Sync  : عند ربط API تجيب كل الطرود النشطة تلقائياً
- Batch Audit   : كل يوم 00:00 تتحقق من كل الطرود بـ batching
- Webhook Setup : تسجل Webhook URL تلقائياً في حساب Yalidine
"""

import time
import logging
from typing import Optional
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from notifications import notify_customer
from config import APP_URL

logger = logging.getLogger("akdili-magic-sync")

# حالات Yalidine الفرنسية اللي تعتبر "مكتملة" — ما نستوردهاش
TERMINAL_STATUSES_FR = {"Livré", "Retourné", "Retour reçu", "Echoué", "Tentative échouée"}
TERMINAL_STATUSES_EN = {"delivered", "returned", "failed"}


# ============================================================
# 1. INITIAL SYNC — عند ربط الـ API
# ============================================================
def initial_sync(carrier_db, db=None) -> dict:
    """
    تجيب كل الطرود النشطة من Yalidine وتضيفها في الـ DB.
    تُستدعى مباشرة بعد حفظ API keys.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    stats = {"imported": 0, "skipped": 0, "errors": 0}

    try:
        from carriers.yalidine import YalidineCarrier
        carrier_obj = YalidineCarrier(
            api_key=carrier_db.api_key or "",
            api_id=getattr(carrier_db, "api_id", "") or ""
        )

        logger.info(f"🔄 Magic Sync — بدأ الاستيراد للتاجر {carrier_db.merchant_id}")

        page = 1
        while True:
            parcels_page, has_more = carrier_obj.get_active_parcels_page(page=page, page_size=50)

            if not parcels_page:
                break

            for p in parcels_page:
                try:
                    tracking = p.get("tracking") or p.get("id") or ""
                    if not tracking:
                        continue

                    # تجاهل الطرود المكتملة
                    raw_status = p.get("last_status") or p.get("status") or ""
                    if raw_status in TERMINAL_STATUSES_FR:
                        stats["skipped"] += 1
                        continue

                    # هل موجود مسبقاً؟
                    existing = db.query(Parcel).filter(
                        Parcel.tracking_number == str(tracking)
                    ).first()

                    if existing:
                        stats["skipped"] += 1
                        continue

                    # Map الحالة
                    normalized = carrier_obj.normalize_status(raw_status) or "at_origin"

                    # إنشاء الطرد
                    new_parcel = Parcel(
                        merchant_id     = carrier_db.merchant_id,
                        carrier_id      = carrier_db.id,
                        tracking_number = str(tracking),
                        customer_name   = p.get("firstname", "") + " " + p.get("familyname", ""),
                        customer_phone  = p.get("contact_phone", "") or p.get("phone", "") or "0000000000",
                        wilaya          = p.get("to_wilaya_name", "") or p.get("last_update_wilaya", ""),
                        delivery_type   = "home" if p.get("product_list") else "office",
                        current_status  = normalized,
                        is_active       = normalized not in TERMINAL_STATUSES_EN,
                    )
                    db.add(new_parcel)
                    db.flush()

                    # أضف TrackingEvent أول مرة
                    event = TrackingEvent(
                        parcel_id   = new_parcel.id,
                        status      = normalized,
                        location    = p.get("last_update_wilaya", ""),
                        description = f"[Magic Sync] استيراد تلقائي — {raw_status}"
                    )
                    db.add(event)
                    stats["imported"] += 1

                except Exception as e:
                    logger.warning(f"⚠️ خطأ في طرد {p.get('tracking','?')}: {e}")
                    stats["errors"] += 1
                    continue

            db.commit()
            logger.info(f"   📄 صفحة {page} — {len(parcels_page)} طرد")

            if not has_more:
                break
            page += 1
            time.sleep(1.1)  # Rate limit: 1000ms

        logger.info(f"✅ Magic Sync اكتمل — مستورد:{stats['imported']} | موجود:{stats['skipped']} | أخطاء:{stats['errors']}")

    except Exception as e:
        logger.error(f"❌ Magic Sync فشل: {e}")
        stats["error_msg"] = str(e)
    finally:
        if close_db:
            db.close()

    return stats


# ============================================================
# 2. DAILY BATCH AUDIT — كل يوم 00:00
# ============================================================
def daily_batch_audit():
    """
    يتحقق من كل الطرود النشطة عبر Batch API (10 tracking numbers لكل request).
    يشتغل كـ cron job كل يوم 00:00.
    """
    db = SessionLocal()
    updated = 0
    errors  = 0

    try:
        logger.info("🌙 Daily Audit — بدأ...")

        # جمع كل الشركات المربوطة
        carriers_db = db.query(Carrier).filter(Carrier.is_connected == True).all()

        for carrier_db in carriers_db:
            if carrier_db.carrier_code != "yalidine":
                continue  # حالياً فقط Yalidine يدعم Batch

            try:
                from carriers.yalidine import YalidineCarrier
                carrier_obj = YalidineCarrier(
                    api_key=carrier_db.api_key or "",
                    api_id=getattr(carrier_db, "api_id", "") or ""
                )

                # جيب كل الطرود النشطة للتاجر
                active_parcels = db.query(Parcel).filter(
                    Parcel.carrier_id == carrier_db.id,
                    Parcel.is_active  == True
                ).all()

                if not active_parcels:
                    continue

                tracking_numbers = [p.tracking_number for p in active_parcels]
                parcel_map       = {p.tracking_number: p for p in active_parcels}

                # Batch: 10 tracking numbers لكل request
                BATCH_SIZE = 10
                for i in range(0, len(tracking_numbers), BATCH_SIZE):
                    batch = tracking_numbers[i:i + BATCH_SIZE]

                    results = carrier_obj.batch_track(batch)

                    for tracking, result in results.items():
                        if not result:
                            continue
                        parcel     = parcel_map.get(tracking)
                        new_status = result.get("status")

                        if not parcel or not new_status:
                            continue

                        if new_status != parcel.current_status:
                            # تحديث + إشعار
                            _update_parcel_and_notify(db, parcel, new_status, result.get("location", ""), source="daily-audit")
                            updated += 1

                    db.commit()
                    time.sleep(1.1)  # Rate limit

            except Exception as e:
                logger.error(f"❌ خطأ في audit للتاجر {carrier_db.merchant_id}: {e}")
                db.rollback()
                errors += 1
                continue

        logger.info(f"✅ Daily Audit اكتمل — محدّث:{updated} | أخطاء:{errors}")

    except Exception as e:
        logger.error(f"❌ Daily Audit فشل: {e}")
    finally:
        db.close()

    return {"updated": updated, "errors": errors}


# ============================================================
# 3. WEBHOOK SETUP — تسجيل Webhook في Yalidine تلقائياً
# ============================================================
def register_yalidine_webhook(carrier_db) -> dict:
    """
    يسجل Webhook URL في حساب Yalidine الخاص بالتاجر.
    Webhook URL: {APP_URL}/webhook/yalidine/{merchant_id}
    """
    try:
        import requests as req_lib
        webhook_url = f"{APP_URL}/webhook/yalidine/{carrier_db.merchant_id}"

        headers = {
            "X-API-ID":     getattr(carrier_db, "api_id", "") or "",
            "X-API-TOKEN":  carrier_db.api_key or "",
            "Content-Type": "application/json"
        }

        # Yalidine API — تسجيل Webhook
        resp = req_lib.post(
            "https://api.yalidine.app/v1/webhooks/",
            headers=headers,
            json={
                "url":    webhook_url,
                "events": ["parcel.created", "parcel.updated", "parcel.status_changed"]
            },
            timeout=15
        )

        if resp.status_code in [200, 201]:
            logger.info(f"✅ Webhook مسجل لـ merchant {carrier_db.merchant_id}: {webhook_url}")
            return {"success": True, "webhook_url": webhook_url}

        # بعض نسخ Yalidine API تستعمل endpoint مختلف
        resp2 = req_lib.put(
            "https://api.yalidine.app/v1/settings/webhook/",
            headers=headers,
            json={"webhook_url": webhook_url},
            timeout=15
        )
        if resp2.status_code in [200, 201, 204]:
            logger.info(f"✅ Webhook (PUT) مسجل لـ merchant {carrier_db.merchant_id}")
            return {"success": True, "webhook_url": webhook_url}

        logger.warning(f"⚠️ Webhook ما تسجلش — HTTP {resp.status_code} | {resp.text[:200]}")
        return {"success": False, "error": f"HTTP {resp.status_code}", "webhook_url": webhook_url}

    except Exception as e:
        logger.error(f"❌ Webhook registration فشل: {e}")
        return {"success": False, "error": str(e)}


# ============================================================
# 4. HELPER — تحديث طرد + إشعار واتساب
# ============================================================
def _update_parcel_and_notify(db, parcel, new_status: str, location: str, source: str = "webhook"):
    """
    يحدث حالة الطرد في الـ DB ويبعث إشعار واتساب.
    مشترك بين الـ webhook والـ audit.
    """
    try:
        # حفظ event
        event = TrackingEvent(
            parcel_id   = parcel.id,
            status      = new_status,
            location    = location,
            description = f"[{source}] {parcel.current_status} → {new_status}"
        )
        db.add(event)

        # إشعار واتساب
        merchant = db.query(Merchant).filter(Merchant.id == parcel.merchant_id).first()
        notif_result = notify_customer(
            phone           = parcel.customer_phone,
            tracking_number = parcel.tracking_number,
            status          = new_status,
            delivery_type   = parcel.delivery_type or "home",
            merchant_name   = merchant.name if merchant else ""
        )

        if notif_result.get("whatsapp_sent"):
            notif = Notification(
                parcel_id = parcel.id,
                channel   = "whatsapp",
                phone     = parcel.customer_phone,
                message   = f"[{source}] إشعار {new_status}",
                status    = "sent"
            )
            db.add(notif)
            event.whatsapp_sent = True

        # تحديث الطرد
        parcel.current_status = new_status
        parcel.wilaya         = location or parcel.wilaya
        if new_status in {"delivered", "returned"}:
            parcel.is_active = False

        logger.info(f"📦 [{source}] {parcel.tracking_number}: → {new_status} | WA:{notif_result.get('whatsapp_sent')}")

    except Exception as e:
        logger.error(f"❌ _update_parcel_and_notify فشل ({parcel.tracking_number}): {e}")
        raise
