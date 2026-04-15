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
            "X-API-ID":     self.api_id,
            "X-API-TOKEN":  self.api_key,
            "Content-Type": "application/json"
        }

    def login_and_get_key(self, email: str, password: str) -> dict:
        """
        Yalidine يستخدم API_ID + API_TOKEN مباشرة
        email    = API_ID   (من لوحة تحكم Yalidine)
        password = API_TOKEN (من لوحة تحكم Yalidine)
        """
        api_id    = email.strip()
        api_token = password.strip()

        if not api_id or not api_token:
            return {"success": False, "error": "أدخل API ID و API Token"}

        # نتحقق من صحة المفاتيح
        try:
            resp = requests.get(
                f"{self.BASE_URL}/parcels/",
                headers={
                    "X-API-ID":     api_id,
                    "X-API-TOKEN":  api_token,
                    "Content-Type": "application/json"
                },
                params={"page_size": 1, "page": 1},
                timeout=15
            )
            # 200 = صح | 404 = صح (ما فيش طرود) | 401 = غلط
            if resp.status_code in [200, 404]:
                return {"success": True, "api_id": api_id, "api_token": api_token}
            elif resp.status_code == 401:
                return {"success": False, "error": "API ID أو Token غلط — تحقق من لوحة Yalidine"}
            else:
                # نقبل حتى لو كان رد غير متوقع
                return {"success": True, "api_id": api_id, "api_token": api_token}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_parcels(self) -> list:
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
        mapping = {
            "En préparation":        "at_origin",
            "Collecté":              "at_origin",
            "En transit":            "in_transit",
            "Arrivé wilaya":         "at_destination",
            "En cours de livraison": "out_for_delivery",
            "Livré":                 "delivered",
            "Tentative échouée":     "failed_attempt",
            "Retourné":              "returned",
            "preparing":             "at_origin",
            "collected":             "at_origin",
            "in_transit":            "in_transit",
            "arrived":               "at_destination",
            "out_for_delivery":      "out_for_delivery",
            "delivered":             "delivered",
            "failed":                "failed_attempt",
            "returned":              "returned",
        }
        return mapping.get(raw_status, "in_transit")
