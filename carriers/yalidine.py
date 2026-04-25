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

    def get_wilayas(self) -> list:
        """جلب قائمة الولايات من Yalidine"""
        try:
            resp = requests.get(
                f"{self.BASE_URL}/wilayas/",
                headers=self._headers(),
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                # يرجع list أو dict فيه data
                if isinstance(data, list):
                    return data
                return data.get("data", [])
            return []
        except Exception:
            return []

    def get_communes(self, wilaya_id: int = None) -> list:
        """جلب قائمة البلديات"""
        try:
            params = {}
            if wilaya_id:
                params["wilaya_id"] = wilaya_id
            resp = requests.get(
                f"{self.BASE_URL}/communes/",
                headers=self._headers(),
                params=params,
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("data", [])
            return []
        except Exception:
            return []

    def create_parcel(self, parcel_data: dict) -> dict:
        """
        إنشاء طرد جديد في Yalidine
        parcel_data يحتوي: firstname, familyname, contact_phone, 
                            to_wilaya_name, to_commune_name, 
                            product_list, price, is_stopdesk, 
                            stopdesk_id, freeshipping, order_id
        """
        try:
            import time as _time, random as _random
            _oid = str(parcel_data.get("order_id") or "").strip()
            if not _oid:
                _oid = f"AKD-{int(_time.time())}-{_random.randint(1000,9999)}"

            do_insurance  = bool(parcel_data.get("do_insurance", False))
            has_exchange  = bool(parcel_data.get("has_exchange", False))
            is_stopdesk   = bool(parcel_data.get("is_stopdesk", False))
            stopdesk_id   = parcel_data.get("stopdesk_id")

            payload = {
                "order_id":           _oid,
                "from_wilaya_name":   parcel_data.get("from_wilaya_name", "Alger"),
                "firstname":          parcel_data.get("firstname", ""),
                "familyname":         parcel_data.get("familyname", ""),
                "contact_phone":      parcel_data.get("contact_phone", ""),
                "address":            parcel_data.get("address", ""),
                "to_commune_name":    parcel_data.get("to_commune_name", ""),
                "to_wilaya_name":     parcel_data.get("to_wilaya_name", ""),
                "product_list":       parcel_data.get("product_list", ""),
                "price":              float(parcel_data.get("price", 0)),
                "do_insurance":       do_insurance,
                "declared_value":     float(parcel_data.get("declared_value", 0)) if do_insurance else 0,
                "height":             float(parcel_data.get("height", 10)),
                "width":              float(parcel_data.get("width", 15)),
                "length":             float(parcel_data.get("length", 20)),
                "weight":             float(parcel_data.get("weight", 0.5)),
                "freeshipping":       bool(parcel_data.get("freeshipping", False)),
                "is_stopdesk":        is_stopdesk,
                "has_exchange":       has_exchange,
                "product_to_collect": parcel_data.get("product_to_collect", "") if has_exchange else "",
            }
            if is_stopdesk and stopdesk_id:
                payload["stopdesk_id"] = int(stopdesk_id)

            resp = requests.post(
                f"{self.BASE_URL}/parcels/",
                headers=self._headers(),
                json=[payload],
                timeout=20
            )
            if resp.status_code in [200, 201]:
                data = resp.json()
                # Yalidine يرجع {"order_id": {"success":true, "tracking":"yal-XXX",...}}
                tracking = ""
                if isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, dict):
                            tracking = val.get("tracking") or val.get("tracking_number") or val.get("id") or ""
                        elif isinstance(val, str) and val.startswith("yal-"):
                            tracking = val
                        if tracking:
                            break
                if not tracking and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    tracking = item.get("tracking") or item.get("tracking_number") or str(item.get("id",""))
                return {"success": True, "tracking": tracking, "raw": data}
            else:
                return {"success": False, "error": resp.text, "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}
