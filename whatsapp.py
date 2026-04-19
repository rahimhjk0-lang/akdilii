"""
whatsapp.py — إرسال رسائل واتساب عبر Green API
"""
import requests
from config import GREEN_API_INSTANCE, GREEN_API_TOKEN, STATUS_MESSAGES


def send_whatsapp(phone: str, message: str) -> dict:
    """
    يبعث رسالة واتساب لرقم الهاتف
    phone: رقم الهاتف بدون + (مثال: 213561234567)
    """
    if not GREEN_API_INSTANCE or not GREEN_API_TOKEN:
        return {"success": False, "error": "Green API غير مضبوط"}

    # تنظيف الرقم
    phone = phone.strip().replace("+", "").replace(" ", "")
    if not phone.startswith("213"):
        phone = "213" + phone.lstrip("0")

    chat_id = f"{phone}@c.us"
    url     = f"https://{GREEN_API_INSTANCE}.api.greenapi.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"

    try:
        resp = requests.post(
            url,
            json={"chatId": chat_id, "message": message},
            timeout=15
        )
        data = resp.json()

        if resp.status_code == 200 and data.get("idMessage"):
            return {"success": True, "id": data["idMessage"]}
        else:
            return {"success": False, "error": str(data)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def send_tracking_notification(phone: str, tracking_number: str, status: str) -> dict:
    """
    يبعث إشعار تلقائي بحسب حالة الطرد
    """
    msg_cfg = STATUS_MESSAGES.get(status)
    if not msg_cfg:
        return {"success": False, "error": "حالة غير معروفة"}

    message = msg_cfg["body"].format(tracking=tracking_number)
    return send_whatsapp(phone, message)
