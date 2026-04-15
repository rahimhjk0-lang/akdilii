# ==========================================
# القاعدة المشتركة لكل شركات التوصيل
# ==========================================

class BaseCarrier:
    """كل شركة توصيل ترث من هذا الكلاس"""
    
    CARRIER_CODE = ""
    CARRIER_NAME = ""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_parcels(self) -> list:
        """جلب كل الطرود النشطة"""
        raise NotImplementedError

    def track_parcel(self, tracking_number: str) -> dict:
        """تتبع طرد واحد"""
        raise NotImplementedError

    def login_and_get_key(self, email: str, password: str) -> str:
        """تسجيل الدخول وجلب المفتاح"""
        raise NotImplementedError

    def normalize_status(self, raw_status: str) -> str:
        """تحويل حالة الشركة للحالة الموحدة"""
        raise NotImplementedError


# الحالات الموحدة
STATUS_MAP = {
    "at_origin":        "at_origin",
    "in_transit":       "in_transit",
    "at_destination":   "at_destination",
    "out_for_delivery": "out_for_delivery",
    "delivered":        "delivered",
    "failed_attempt":   "failed_attempt",
    "returned":         "returned",
}
