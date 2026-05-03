"""
Magic Sync Service — Self-Aware Rate Limiter
=============================================
- Initial Sync  : يجيب كل الطرود النشطة صفحة بصفحة (sleep 1.3s بين كل صفحة)
- Daily Audit   : Batch 10 tracking/request مع header-aware throttle
- Webhook Setup : يسجل Webhook URL تلقائياً في حساب Yalidine
"""

import time
import logging
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification, Merchant
from notifications import notify_customer
from config import APP_URL

logger = logging.getLogger("akdili-magic-sync")

TERMINAL_STATUSES_FR = {"Livré", "Retourné", "Retour reçu", "Echoué", "Tentative échouée"}
TERMINAL_STATUSES_EN = {"delivered", "returned", "failed"}

# sleep إجباري بين صفحات الـ Initial Sync (أقل من 50 req/min)
INITIAL_SYNC_PAGE_SLEEP = 1.3


# ============================================================
# 1. INITIAL SYNC — عند ربط الـ API
# ============================================================
def initial_sync(carrier_db, db=None) -> dict:
    """
    يجيب كل الطرود النشطة من Yalidine ويضيفها في الـ DB.
    - sleep 1.3s بين كل صفحة (50 req/min safe)
    - QuotaGuard في YalidineCarrier يتكفل بـ per-request throttle
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
            # QuotaGuard يتكفل بـ throttle داخل get_active_parcels_page
            parcels_page, has_more = carrier_obj.get_active_parcels_page(
                page=page, page_size=50
            )

            if not parcels_page and not has_more:
                logger.info(f"[SYNC] صفحة {page} فارغة أو آخر صفحة — نوقف")
                break

            for p in parcels_page:
                try:
                    tracking = p.get("tracking") or p.get("id") or ""
                    if not tracking:
                        continue

                    raw_status = p.get("last_status") or p.get("status") or ""
                    if raw_status in TERMINAL_STATUSES_FR:
                        stats["skipped"] += 1
                        continue

                    existing = db.query(Parcel).filter(
                        Parcel.tracking_number == str(tracking)
                    ).first()
                    if existing:
                        stats["skipped"] += 1
                        continue

                    normalized = carrier_obj.normalize_status(raw_status) or "at_origin"

                    new_parcel = Parcel(
                        merchant_id     = carrier_db.merchant_id,
                        carrier_id      = carrier_db.id,
                        tracking_number = str(tracking),
                        customer_name   = (
                            (p.get("firstname", "") or "") + " " +
                            (p.get("familyname", "") or "")
                        ).strip() or "زبون",
                        customer_phone  = (
                            p.get("contact_phone") or
                            p.get("phone") or
                            "0000000000"
                        ),
                        wilaya          = (
                            p.get("to_wilaya_name") or
                            p.get("last_update_wilaya") or ""
                        ),
                        delivery_type   = (
                            "home" if p.get("product_list") else "office"
                        ),
                        current_status  = normalized,
                        is_active       = normalized not in TERMINAL_STATUSES_EN,
                    )
                    db.add(new_parcel)
                    db.flush()

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

            quota_min = carrier_obj.quota.min_left
            logger.info(
                f"[SYNC] ✅ صفحة {page} | "
                f"مستورد:{stats['imported']} skipped:{stats['skipped']} | "
                f"quota_min={quota_min}"
            )

            if not has_more:
                break

            # ── sleep إجباري بين الصفحات (بالإضافة لـ QuotaGuard) ──
            # إذا minute quota حرج → QuotaGuard نامت 65s داخل _safe_get
            # هنا sleep إضافي ثابت 1.3s بين صفحات الـ pagination
            if quota_min >= 5:
                time.sleep(INITIAL_SYNC_PAGE_SLEEP)

            page += 1

        logger.info(
            f"✅ Magic Sync اكتمل — "
            f"مستورد:{stats['imported']} | موجود:{stats['skipped']} | أخطاء:{stats['errors']}"
        )

    except Exception as e:
        logger.error(f"❌ Magic Sync فشل: {e}")
        stats["error_msg"] = str(e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if close_db:
            db.close()

    return stats


# ============================================================
# 2. DAILY BATCH AUDIT — كل يوم 00:00
# ============================================================
def daily_batch_audit() -> dict:
    """
    يتحقق من كل الطرود النشطة عبر Batch API (10 tracking/request).
    QuotaGuard في YalidineCarrier يتكفل بـ header-aware throttle.
    """
    db      = SessionLocal()
    updated = 0
    errors  = 0

    try:
        logger.info("🌙 Daily Audit — بدأ...")

        carriers_db = db.query(Carrier).filter(Carrier.is_connected == True).all()

        for carrier_db in carriers_db:
            if carrier_db.carrier_code != "yalidine":
                continue

            try:
                from carriers.yalidine import YalidineCarrier
                carrier_obj = YalidineCarrier(
                    api_key=carrier_db.api_key or "",
                    api_id=getattr(carrier_db, "api_id", "") or ""
                )

                active_parcels = db.query(Parcel).filter(
                    Parcel.carrier_id == carrier_db.id,
                    Parcel.is_active  == True
                ).all()

                if not active_parcels:
                    continue

                tracking_numbers = [p.tracking_number for p in active_parcels]
                parcel_map       = {p.tracking_number: p for p in active_parcels}

                logger.info(
                    f"[AUDIT] التاجر {carrier_db.merchant_id} — "
                    f"{len(tracking_numbers)} طرد نشط"
                )

                # ── Batch 10 tracking numbers لكل request ──
                BATCH_SIZE = 10
                for i in range(0, len(tracking_numbers), BATCH_SIZE):
                    batch = tracking_numbers[i : i + BATCH_SIZE]

                    # batch_track → _safe_get → QuotaGuard يتكفل بـ throttle
                    results = carrier_obj.batch_track(batch)

                    for tracking, result in results.items():
                        if not result:
                            continue
                        parcel     = parcel_map.get(tracking)
                        new_status = result.get("status")

                        if not parcel or not new_status:
                            continue

                        if new_status != parcel.current_status:
                            _update_parcel_and_notify(
                                db, parcel,
                                new_status,
                                result.get("location", ""),
                                source="daily-audit"
                            )
                            updated += 1

                    db.commit()

                    logger.info(
                        f"[AUDIT] Batch {i//BATCH_SIZE + 1} | "
                        f"quota_min={carrier_obj.quota.min_left} | "
                        f"quota_sec={carrier_obj.quota.sec_left}"
                    )

            except Exception as e:
                logger.error(f"❌ خطأ في audit التاجر {carrier_db.merchant_id}: {e}")
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
# 3. WEBHOOK SETUP — تسجيل Webhook في Yalidine
# ============================================================
def register_yalidine_webhook(carrier_db) -> dict:
    """
    يسجل Webhook URL في حساب Yalidine الخاص بالتاجر.
    URL: {APP_URL}/webhook/yalidine/{merchant_id}
    """
    import requests as req_lib

    webhook_url = f"{APP_URL}/webhook/yalidine/{carrier_db.merchant_id}"
    headers     = {
        "X-API-ID":     getattr(carrier_db, "api_id", "") or "",
        "X-API-TOKEN":  carrier_db.api_key or "",
        "Content-Type": "application/json",
    }

    # محاولة 1: POST /webhooks/
    try:
        resp = req_lib.post(
            "https://api.yalidine.app/v1/webhooks/",
            headers=headers,
            json={
                "url":    webhook_url,
                "events": ["parcel.created", "parcel.updated", "parcel.status_changed"],
            },
            timeout=15,
        )
        if resp.status_code in [200, 201]:
            logger.info(f"✅ Webhook (POST) مسجل: {webhook_url}")
            return {"success": True, "webhook_url": webhook_url}
    except Exception as e:
        logger.warning(f"⚠️ Webhook POST error: {e}")

    # محاولة 2: PUT /settings/webhook/
    try:
        resp2 = req_lib.put(
            "https://api.yalidine.app/v1/settings/webhook/",
            headers=headers,
            json={"webhook_url": webhook_url},
            timeout=15,
        )
        if resp2.status_code in [200, 201, 204]:
            logger.info(f"✅ Webhook (PUT) مسجل: {webhook_url}")
            return {"success": True, "webhook_url": webhook_url}

        logger.warning(f"⚠️ Webhook PUT HTTP {resp2.status_code} | {resp2.text[:150]}")

    except Exception as e:
        logger.warning(f"⚠️ Webhook PUT error: {e}")

    # الـ Webhook URL صحيح حتى لو التسجيل فشل —
    # التاجر يقدر يضيفه يدوياً في لوحة Yalidine
    return {
        "success": False,
        "webhook_url": webhook_url,
        "note": "سجّل هذا الرابط يدوياً في لوحة Yalidine",
    }


# ============================================================
# 4. HELPER — تحديث طرد + إشعار واتساب
# ============================================================
def _update_parcel_and_notify(db, parcel, new_status: str, location: str, source: str = "webhook"):
    """
    يحدّث حالة الطرد ويبعث واتساب.
    مشترك بين الـ webhook والـ daily audit.
    """
    try:
        event = TrackingEvent(
            parcel_id   = parcel.id,
            status      = new_status,
            location    = location,
            description = f"[{source}] {parcel.current_status} → {new_status}",
        )
        db.add(event)

        merchant     = db.query(Merchant).filter(Merchant.id == parcel.merchant_id).first()
        notif_result = notify_customer(
            phone           = parcel.customer_phone,
            tracking_number = parcel.tracking_number,
            status          = new_status,
            delivery_type   = parcel.delivery_type or "home",
            merchant_name   = merchant.name if merchant else "",
        )

        if notif_result.get("whatsapp_sent"):
            db.add(Notification(
                parcel_id = parcel.id,
                channel   = "whatsapp",
                phone     = parcel.customer_phone,
                message   = f"[{source}] إشعار {new_status}",
                status    = "sent",
            ))
            event.whatsapp_sent = True

        if notif_result.get("sms_sent"):
            db.add(Notification(
                parcel_id = parcel.id,
                channel   = "sms",
                phone     = parcel.customer_phone,
                message   = f"[{source}] SMS {new_status}",
                status    = "sent",
            ))
            event.sms_sent = True

        parcel.current_status = new_status
        parcel.wilaya         = location or parcel.wilaya
        if new_status in {"delivered", "returned"}:
            parcel.is_active = False

        logger.info(
            f"📦 [{source}] {parcel.tracking_number}: → {new_status} | "
            f"WA:{notif_result.get('whatsapp_sent')} | SMS:{notif_result.get('sms_sent')}"
        )

    except Exception as e:
        logger.error(f"❌ _update_parcel_and_notify ({parcel.tracking_number}): {e}")
        raise
