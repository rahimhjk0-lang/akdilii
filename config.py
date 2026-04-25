# ==========================================
# Akdili — اكدلي
# منصة تتبع الطرود والإشعارات التلقائية
# ==========================================

import os
from dotenv import load_dotenv

load_dotenv()

# ---- الإعدادات الأساسية ----
APP_NAME    = "اكدلي - Akdili"
APP_VERSION = "1.0.0"
SECRET_KEY    = os.getenv("SECRET_KEY", "akdili-secret-key-change-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "akdili2026")

# ---- قاعدة البيانات ----
_db_url = os.getenv("DATABASE_URL", "sqlite:///./akdili.db").strip()
# Render يبعث postgres:// لكن SQLAlchemy يحتاج postgresql://
DATABASE_URL = _db_url.replace("postgres://", "postgresql://", 1) if _db_url.startswith("postgres://") else _db_url

# ---- Chargily Pay ----
CHARGILY_API_KEY        = os.getenv("CHARGILY_API_KEY", "")
CHARGILY_WEBHOOK_SECRET = os.getenv("CHARGILY_WEBHOOK_SECRET", "")
APP_URL                 = os.getenv("APP_URL", "https://akdilii.onrender.com")

# ---- Green API واتساب ----
GREEN_API_INSTANCE = os.getenv("GREEN_API_INSTANCE", "").strip()
GREEN_API_TOKEN    = os.getenv("GREEN_API_TOKEN", "").strip()

# ---- SMS ----
SMS_API_KEY = os.getenv("SMS_API_KEY", "")
SMS_SENDER  = os.getenv("SMS_SENDER", "Akdili")

# ---- الجدولة ----
TRACKING_INTERVAL_HOURS = 0  # غير مستعمل
TRACKING_INTERVAL_MINUTES = 30  # كل 30 دقيقة

# ---- الباقات ----
PLANS = {
    "free":       {"name": "مجاني",      "orders": 30,    "price": 0,     "price_dz": "مجاني"},
    "starter":    {"name": "Starter",    "orders": 250,   "price": 2900,  "price_dz": "2,900 دج"},
    "growth":     {"name": "Growth",     "orders": 500,   "price": 4900,  "price_dz": "4,900 دج"},
    "pro":        {"name": "Pro",        "orders": 1000,  "price": 9900,  "price_dz": "9,900 دج"},
    "business":   {"name": "Business",  "orders": 5000,  "price": 14900, "price_dz": "14,900 دج"},
    "unlimited":  {"name": "غير محدود", "orders": 99999, "price": 17900, "price_dz": "17,900 دج"},
}

# ---- شركات التوصيل ----
CARRIERS = {
    "yalidine":   {"name": "Yalidine Express",  "logo": "yalidine.png"},
    "zr_express": {"name": "ZR Express",         "logo": "zr.png"},
    "ecotrack":   {"name": "Ecotrack",           "logo": "ecotrack.png"},
    "procolis":   {"name": "Procolis",           "logo": "procolis.png"},
    "maystro":    {"name": "Maystro Delivery",   "logo": "maystro.png"},
    "guepex":        {"name": "Guepex",             "logo": "guepex.png"},
    "ecom_delivery": {"name": "E-com Delivery",    "logo": "ecom.png"},
}

# ---- حالات الطرد ----
# الحالات اللي تبعث فيها واتساب
WHATSAPP_STATUSES = [
    "at_origin",       # وصل مكتب الإرسال
    "in_transit",      # في الطريق
    "at_destination",  # وصل مكتب الوصول
    "out_for_delivery",# عند الساعي (منزل فقط)
    "delivered",       # تم التسليم
    "failed_attempt",  # محاولة فاشلة
]

# الحالات اللي تبعث فيها SMS إذا فشل واتساب
SMS_STATUSES = [
    "in_transit",       # في الطريق ← مهم باش يستعد
    "at_destination",   # وصل المكتب
    "out_for_delivery", # عند الساعي
    "delivered",        # تم التسليم
    "failed_attempt",   # محاولة فاشلة
]

# رسايل كل حالة
STATUS_MESSAGES = {
    "at_origin": {
        "title": "📦 طردك وصل مكتب الإرسال",
        "body": "طردك رقم {tracking} وصل مكتب الإرسال وجاري التجهيز للشحن ✅"
    },
    "in_transit": {
        "title": "🚚 طردك في الطريق",
        "body": "طردك رقم {tracking} انطلق وفي طريقه إليك 🚚\nاستعد للاستلام قريباً!"
    },
    "at_destination": {
        "title": "🏢 طردك وصل مكتبنا",
        "body": "طردك رقم {tracking} وصل مكتبنا في ولايتك ✅\nسيُسلَّم لك قريباً 🏠"
    },
    "out_for_delivery": {
        "title": "🛵 طردك عند الساعي",
        "body": "طردك رقم {tracking} عند الساعي الآن 🛵\nسيصلك اليوم — كن متواجداً ✅"
    },
    "delivered": {
        "title": "✅ تم تسليم طردك",
        "body": "✅ تم تسليم طردك رقم {tracking} بنجاح\nشكراً على ثقتك 🙏"
    },
    "failed_attempt": {
        "title": "⚠️ محاولة تسليم فاشلة",
        "body": "حاولنا نوصلوا طردك رقم {tracking} 😕\nما لقيناكش — تواصل معنا باش نرتبوا\nوإلا يرجع للمرسل ⚠️"
    },
}
