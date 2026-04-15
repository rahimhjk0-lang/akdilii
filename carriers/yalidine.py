import requests
from carriers import BaseCarrier

class YalidineCarrier(BaseCarrier):

    CARRIER_CODE = "yalidine"
    CARRIER_NAME = "Yalidine Express"
    BASE_URL     = "https://api.yalidine.app/v1"

    def __init__(self, api_key: str, api_id: str = ""):
        super().__init__(api_key)
        self.api_id = api_id

    def _headers(self):
        return {
            "X-API-ID":    self.api_id,
            "X-API-TOKEN": self.api_key,
            "Content-Type": "application/json"
        }

    def login_and_get_key(self, email: str, password: str) -> dict:
        """
        تسجيل الدخول بالإيميل وكلمة السر
        وجلب API Key تلقائياً
        """
        try:
            session = requests.Session()

            # الخطوة 1: تسجيل الدخول
            login_resp = session.post(
                "https://app.yalidine.app/api/auth/login",
                json={"email": email, "password": password},
                timeout=15
            )

            if login_resp.status_code != 200:
                return {"success": False, "error": "إيميل أو كلمة سر غلطة"}

            data = login_resp.json()
            token = data.get("token") or data.get("access_token")

            if not token:
                return {"success": False, "error": "فشل تسجيل الدخول"}

            # الخطوة 2: جلب المفتاح من الإعدادات
            settings_resp = session.get(
                "https://app.yalidine.app/api/user/api-keys",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )

            if settings_resp.status_code == 200:
                keys_data = settings_resp.json()
                api_id    = keys_data.get("api_id",    "")
                api_token = keys_data.get("api_token", "")
                return {
                    "success":   True,
                    "api_id":    api_id,
                    "api_token": api_token
                }

            return {"success": False, "error": "ما قدرناش نجيب المفتاح"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_parcels(self) -> list:
        """جلب كل الطرود النشطة"""
        try:
            resp = requests.get(
                f"{self.BASE_URL}/parcels/",
                headers=self._headers(),
                params={"page_size": 200, "page": 1},
                timeout=20
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
            return []
        except Exception:
            return []

    def track_parcel(self, tracking_number: str) -> dict:
        """تتبع طرد واحد"""
        try:
            resp = requests.get(
                f"{self.BASE_URL}/parcels/{tracking_number}/",
                headers=self._headers(),
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "tracking_number": tracking_number,
                    "status":   self.normalize_status(data.get("status", "")),
                    "location": data.get("last_update_wilaya", ""),
                    "raw":      data
                }
            return {}
        except Exception:
            return {}

    def normalize_status(self, raw_status: str) -> str:
        """تحويل حالات Yalidine للحالات الموحدة"""
        mapping = {
            # Yalidine statuses → حالات موحدة
            "En préparation":          "at_origin",
            "Collecté":                "at_origin",
            "En transit":              "in_transit",
            "Arrivé wilaya":           "at_destination",
            "En cours de livraison":   "out_for_delivery",
            "Livré":                   "delivered",
            "Tentative échouée":       "failed_attempt",
            "Retourné":                "returned",
            # English variants
            "preparing":               "at_origin",
            "collected":               "at_origin",
            "in_transit":              "in_transit",
            "arrived":                 "at_destination",
            "out_for_delivery":        "out_for_delivery",
            "delivered":               "delivered",
            "failed":                  "failed_attempt",
            "returned":                "returned",
        }
        return mapping.get(raw_status, "in_transit")
