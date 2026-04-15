import requests
from carriers import BaseCarrier

class ZRExpressCarrier(BaseCarrier):

    CARRIER_CODE = "zr_express"
    CARRIER_NAME = "ZR Express"
    BASE_URL     = "https://api.zrexpress.app/api"

    def login_and_get_key(self, email: str, password: str) -> dict:
        try:
            session = requests.Session()
            resp = session.post(
                f"{self.BASE_URL}/auth/login",
                json={"email": email, "password": password},
                timeout=15
            )
            if resp.status_code == 200:
                data  = resp.json()
                token = data.get("token") or data.get("access_token")
                if token:
                    return {"success": True, "api_token": token, "api_id": ""}
            return {"success": False, "error": "إيميل أو كلمة سر غلطة"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_parcels(self) -> list:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/parcels",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20
            )
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except Exception:
            return []

    def track_parcel(self, tracking_number: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/parcels/{tracking_number}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "tracking_number": tracking_number,
                    "status":   self.normalize_status(data.get("status", "")),
                    "location": data.get("wilaya", ""),
                    "raw":      data
                }
            return {}
        except Exception:
            return {}

    def normalize_status(self, raw_status: str) -> str:
        mapping = {
            "pending":           "at_origin",
            "picked_up":         "at_origin",
            "in_transit":        "in_transit",
            "at_hub":            "at_destination",
            "out_for_delivery":  "out_for_delivery",
            "delivered":         "delivered",
            "failed":            "failed_attempt",
            "returned":          "returned",
        }
        return mapping.get(raw_status, "in_transit")
