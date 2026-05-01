from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import SessionLocal
from models import Parcel, Carrier, TrackingEvent, Notification
from carriers.all_carriers import get_carrier
from notifications import notify_customer
from config import TRACKING_INTERVAL_MINUTES
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("akdili-scheduler")

# ==========================================
# الوظيفة الرئيسية — تشتغل كل 5 ساعات
# ==========================================
def check_all_parcels():
    """يتحقق من كل الطرود النشطة ويبعث إشعارات"""

    db = SessionLocal()
    updated_count = 0

    try:
        # جلب كل الطرود النشطة (مش مسلمة ومش مرتجعة)
        active_parcels = db.query(Parcel).filter(
            Parcel.is_active == True,
            ~Parcel.current_status.in_(["delivered", "returned"])
        ).all()

        logger.info(f"🔍 نتحقق من {len(active_parcels)} طرد...")

        for parcel in active_parcels:
            try:
                # جلب الشركة المربوطة
                carrier_db = db.query(Carrier).filter(
                    Carrier.id == parcel.carrier_id,
                    Carrier.is_connected == True
                ).first()

                if not carrier_db:
                    continue

                # تتبع الطرد
                carrier = get_carrier(
                    carrier_code=carrier_db.carrier_code,
                    api_key=carrier_db.api_key or "",
                    api_id=getattr(carrier_db, "api_id", "")
                )

                result = carrier.track_parcel(parcel.tracking_number)

                if not result:
                    continue

                new_status = result.get("status")   # None إذا حالة مجهولة أو فارغة
                location   = result.get("location", "")

                # ✅ شرط صارم: حالة صحيحة + تغيرت فعلاً
                if not new_status:
                    logger.info(f"⏭ {parcel.tracking_number}: لا حالة من API — نتجاهل")
                    continue

                logger.info(f"[TRACKING] {parcel.tracking_number}: حالة API={repr(new_status)} | DB={repr(parcel.current_status)}")

                if new_status != parcel.current_status:
                    logger.info(f"📦 {parcel.tracking_number}: {parcel.current_status} → {new_status}")

                    # حفظ التحديث في قاعدة البيانات
                    event = TrackingEvent(
                        parcel_id   = parcel.id,
                        status      = new_status,
                        location    = location,
                        description = f"تحديث تلقائي: {new_status}"
                    )
                    db.add(event)

                    # إرسال الإشعار للزبون
                    notif_result = notify_customer(
                        phone           = parcel.customer_phone,
                        tracking_number = parcel.tracking_number,
                        status          = new_status,
                        delivery_type   = parcel.delivery_type,
                        merchant_name   = parcel.merchant.name if parcel.merchant else ""
                    )

                    # حفظ سجل الإشعار
                    if notif_result.get("whatsapp_sent"):
                        notif = Notification(
                            parcel_id = parcel.id,
                            channel   = "whatsapp",
                            phone     = parcel.customer_phone,
                            message   = f"إشعار {new_status}",
                            status    = "sent"
                        )
                        db.add(notif)
                        event.whatsapp_sent = True

                    if notif_result.get("sms_sent"):
                        notif = Notification(
                            parcel_id = parcel.id,
                            channel   = "sms",
                            phone     = parcel.customer_phone,
                            message   = f"إشعار {new_status}",
                            status    = "sent"
                        )
                        db.add(notif)
                        event.sms_sent = True

                    # تحديث حالة الطرد
                    parcel.current_status = new_status
                    parcel.wilaya         = location

                    # إذا سُلّم أو رجع → أوقف التتبع
                    if new_status in ["delivered", "returned"]:
                        parcel.is_active = False

                    updated_count += 1
                    db.commit()

            except Exception as e:
                logger.error(f"❌ خطأ في طرد {parcel.tracking_number}: {e}")
                db.rollback()
                continue

        logger.info(f"✅ انتهى التحقق — {updated_count} طرد تحدّث")

    except Exception as e:
        logger.error(f"❌ خطأ في الجدولة: {e}")
    finally:
        db.close()


# ==========================================
# تشغيل الجدولة
# ==========================================
scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(
        func    = check_all_parcels,
        trigger = IntervalTrigger(minutes=TRACKING_INTERVAL_MINUTES),
        id      = "track_parcels",
        name    = f"تتبع الطرود كل {TRACKING_INTERVAL_MINUTES} دقيقة",
        replace_existing = True
    )
    scheduler.start()
    logger.info(f"⏰ الجدولة شغالة — كل {TRACKING_INTERVAL_MINUTES} دقيقة")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("⏹ الجدولة وقفت")
