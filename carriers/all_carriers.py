import requests
from carriers import BaseCarrier

class EcotrackCarrier(BaseCarrier):
    CARRIER_CODE = "ecotrack"
    CARRIER_NAME = "Ecotrack"
    BASE_URL     = "https://ecotrack.dz/api/v1"

    def login_and_get_key(self, email: str, password: str) -> dict:
        try:
            resp = requests.post(
                f"{self.BASE_URL}/login",
                json={"email": email, "password": password},
                timeout=15
            )
            if resp.status_code == 200:
                data  = resp.json()
                token = data.get("api_key") or data.get("token")
                if token:
                    return {"success": True, "api_token": token, "api_id": ""}
            return {"success": False, "error": "إيميل أو كلمة سر غلطة"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def track_parcel(self, tracking_number: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/shipments/{tracking_number}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "tracking_number": tracking_number,
                    "status":   self.normalize_status(data.get("status", "")),
                    "location": data.get("location", ""),
                    "raw":      data
                }
            return {}
        except Exception:
            return {}

    def get_parcels(self) -> list:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/shipments",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20
            )
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except Exception:
            return []

    def normalize_status(self, raw_status: str) -> str:
        mapping = {
            "created":        "at_origin",
            "transit":        "in_transit",
            "hub":            "at_destination",
            "delivering":     "out_for_delivery",
            "delivered":      "delivered",
            "failed":         "failed_attempt",
            "returned":       "returned",
        }
        return mapping.get(raw_status, "in_transit")


class ProcolisCarrier(BaseCarrier):
    CARRIER_CODE = "procolis"
    CARRIER_NAME = "Procolis"
    BASE_URL     = "https://app.procolis.com/api"

    def login_and_get_key(self, email: str, password: str) -> dict:
        try:
            resp = requests.post(
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

    def track_parcel(self, tracking_number: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/tracking/{tracking_number}",
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

    def normalize_status(self, raw_status: str) -> str:
        mapping = {
            "new":            "at_origin",
            "transit":        "in_transit",
            "arrived":        "at_destination",
            "delivering":     "out_for_delivery",
            "delivered":      "delivered",
            "undelivered":    "failed_attempt",
            "returned":       "returned",
        }
        return mapping.get(raw_status, "in_transit")


class MaystroCarrier(BaseCarrier):
    CARRIER_CODE = "maystro"
    CARRIER_NAME = "Maystro Delivery"
    BASE_URL     = "https://api.maystro.dz/v1"

    def login_and_get_key(self, email: str, password: str) -> dict:
        try:
            resp = requests.post(
                f"{self.BASE_URL}/auth/login",
                json={"email": email, "password": password},
                timeout=15
            )
            if resp.status_code == 200:
                data  = resp.json()
                token = data.get("access") or data.get("token")
                if token:
                    return {"success": True, "api_token": token, "api_id": ""}
            return {"success": False, "error": "إيميل أو كلمة سر غلطة"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def track_parcel(self, tracking_number: str) -> dict:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/orders/{tracking_number}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "tracking_number": tracking_number,
                    "status":   self.normalize_status(data.get("status", "")),
                    "location": data.get("commune", ""),
                    "raw":      data
                }
            return {}
        except Exception:
            return {}

    def get_parcels(self) -> list:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/orders",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20
            )
            return resp.json().get("results", []) if resp.status_code == 200 else []
        except Exception:
            return []

    def normalize_status(self, raw_status: str) -> str:
        mapping = {
            "TO_PREPARE":   "at_origin",
            "TO_SHIP":      "in_transit",
            "SHIPPED":      "in_transit",
            "AT_HUB":       "at_destination",
            "TO_DELIVER":   "out_for_delivery",
            "DELIVERED":    "delivered",
            "FAILED":       "failed_attempt",
            "RETURNED":     "returned",
        }
        return mapping.get(raw_status, "in_transit")


class GuepexCarrier(BaseCarrier):
    CARRIER_CODE = "guepex"
    CARRIER_NAME = "Guepex"
    BASE_URL     = "https://api.guepex.app/v1"

    def login_and_get_key(self, email: str, password: str) -> dict:
        try:
            resp = requests.post(
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

    def normalize_status(self, raw_status: str) -> str:
        mapping = {
            "pending":     "at_origin",
            "transit":     "in_transit",
            "arrived":     "at_destination",
            "delivery":    "out_for_delivery",
            "delivered":   "delivered",
            "failed":      "failed_attempt",
            "returned":    "returned",
        }
        return mapping.get(raw_status, "in_transit")


# ==========================================
# Factory — جلب الشركة المناسبة بالاسم
# ==========================================
from carriers.yalidine  import YalidineCarrier
from carriers.zr_express import ZRExpressCarrier

CARRIER_CLASSES = {
    "yalidine":   YalidineCarrier,
    "zr_express": ZRExpressCarrier,
    "ecotrack":   EcotrackCarrier,
    "procolis":   ProcolisCarrier,
    "maystro":    MaystroCarrier,
    "guepex":     GuepexCarrier,
}

def get_carrier(carrier_code: str, api_key: str, api_id: str = ""):
    cls = CARRIER_CLASSES.get(carrier_code)
    if not cls:
        raise ValueError(f"شركة غير معروفة: {carrier_code}")
    if carrier_code == "yalidine":
        return cls(api_key=api_key, api_id=api_id)
    return cls(api_key=api_key)
