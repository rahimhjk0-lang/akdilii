import requests
from config import ULTRAMSG_INSTANCE, ULTRAMSG_TOKEN, STATUS_MESSAGES, WHATSAPP_STATUSES, SMS_STATUSES

# ==========================================
# إرسال واتساب عبر UltraMsg
# ==========================================
def send_whatsapp(phone: str, message: str) -> bool:
    """يبعث رسالة واتساب — يرجع True إذا نجح"""
    try:
        if not ULTRAMSG_INSTANCE or not ULTRAMSG_TOKEN:
            print("⚠️ UltraMsg غير مضبوط")
            return False

        # تنظيف الرقم
        phone = clean_phone(phone)

        resp = requests.post(
            f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat",
            data={
                "token": ULTRAMSG_TOKEN,
                "to":    phone,
                "body":  message
            },
            timeout=10
        )

        result = resp.json()
        if result.get("sent") == "true" or result.get("id"):
            print(f"✅ واتساب وصل → {phone}")
            return True
        else:
            print(f"❌ واتساب فشل → {phone} | {result}")
            return False

    except Exception as e:
        print(f"❌ خطأ واتساب: {e}")
        return False


# ==========================================
# إرسال SMS
# ==========================================
def send_sms(phone: str, message: str) -> bool:
    """يبعث SMS — يرجع True إذا نجح"""
    try:
        from config import SMS_API_KEY, SMS_SENDER

        if not SMS_API_KEY:
            print("⚠️ SMS API غير مضبوط")
            return False

        phone = clean_phone(phone)

        # تقصير الرسالة للـ SMS
        short_message = message[:160]

        resp = requests.post(
            "https://api.sms-algerie.net/send",
            data={
                "apikey":  SMS_API_KEY,
                "sender":  SMS_SENDER,
                "mobile":  phone,
                "message": short_message
            },
            timeout=10
        )

        if resp.status_code == 200:
            print(f"✅ SMS وصل → {phone}")
            return True
        else:
            print(f"❌ SMS فشل → {phone} | {resp.text}")
            return False

    except Exception as e:
        print(f"❌ خطأ SMS: {e}")
        return False


# ==========================================
# الدالة الرئيسية — واتساب أولاً ثم SMS
# ==========================================
def notify_customer(
    phone:           str,
    tracking_number: str,
    status:          str,
    delivery_type:   str = "home",
    merchant_name:   str = ""
) -> dict:
    """
    يبعث إشعار للزبون:
    1. واتساب في كل تحديث
    2. SMS فقط إذا فشل الواتساب + الحالة مهمة
    """

    # شوف إذا هذي الحالة تستاهل إشعار
    if status not in WHATSAPP_STATUSES:
        return {"sent": False, "reason": "حالة لا تستاهل إشعار"}

    # إذا كان للمكتب ما نبعثش "عند الساعي"
    if delivery_type == "office" and status == "out_for_delivery":
        return {"sent": False, "reason": "مكتب — ما فيش ساعي"}

    # جهز الرسالة
    msg_template = STATUS_MESSAGES.get(status, {})
    if not msg_template:
        return {"sent": False, "reason": "ما فيش رسالة لهذي الحالة"}

    message = msg_template["body"].format(tracking=tracking_number)

    # أضف اسم التاجر إذا موجود
    if merchant_name:
        message = f"*{merchant_name}*\n\n" + message

    result = {
        "status":         status,
        "whatsapp_sent":  False,
        "sms_sent":       False,
    }

    # ---- الخطوة 1: حاول واتساب ----
    whatsapp_ok = send_whatsapp(phone, message)
    result["whatsapp_sent"] = whatsapp_ok

    # ---- الخطوة 2: SMS إذا فشل واتساب + الحالة مهمة ----
    if not whatsapp_ok and status in SMS_STATUSES:
        # رسالة SMS أقصر وبدون إيموجي
        sms_message = clean_for_sms(message)
        sms_ok = send_sms(phone, sms_message)
        result["sms_sent"] = sms_ok

    result["sent"] = result["whatsapp_sent"] or result["sms_sent"]
    return result


# ==========================================
# دوال مساعدة
# ==========================================
def clean_phone(phone: str) -> str:
    """تنظيف رقم الهاتف"""
    phone = phone.strip().replace(" ", "").replace("-", "")

    # إذا يبدأ بـ 0 → حوله لـ 213
    if phone.startswith("0"):
        phone = "213" + phone[1:]

    # إذا ما فيهش كود الدولة
    if not phone.startswith("+") and not phone.startswith("213"):
        phone = "213" + phone

    # أضف + في البداية
    if not phone.startswith("+"):
        phone = "+" + phone

    return phone


def clean_for_sms(message: str) -> str:
    """تنظيف الرسالة للـ SMS (بدون إيموجي)"""
    import re
    # حذف الإيموجي
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    return emoji_pattern.sub("", message).strip()
