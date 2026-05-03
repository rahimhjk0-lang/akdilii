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

                # ✅ نقرأ last_status أولاً — هي الحالة الحقيقية من Yalidine
                raw_status = data.get("last_status") or data.get("status") or ""
                print(f"[YALIDINE DEBUG] {tracking_number} | last_status={repr(data.get('last_status'))} | status={repr(data.get('status'))} | raw_used={repr(raw_status)}")

                # إذا الحالة الخام فارغة → لا نغير شيء
                if not raw_status:
                    print(f"[YALIDINE DEBUG] {tracking_number} — حالة فارغة، نتجاهل")
                    return {
                        "tracking_number": tracking_number,
                        "status":   None,
                        "location": data.get("last_update_wilaya", ""),
                        "raw":      data
                    }

                normalized = self.normalize_status(raw_status)

                # إذا normalize رجعت None → حالة مجهولة، لا نغير
                if normalized is None:
                    return {
                        "tracking_number": tracking_number,
                        "status":   None,
                        "location": data.get("last_update_wilaya", ""),
                        "raw":      data
                    }

                return {
                    "tracking_number": tracking_number,
                    "status":   normalized,
                    "location": data.get("last_update_wilaya", ""),
                    "raw":      data
                }
            print(f"[YALIDINE DEBUG] {tracking_number} HTTP {resp.status_code}")
            return {}
        except Exception as e:
            print(f"[YALIDINE DEBUG] {tracking_number} exception: {e}")
            return {}

    def normalize_status(self, raw_status: str):
        """
        ✅ Mapping صارم — لا fallback افتراضي.
        حالة مجهولة → يرجع None (لا تغيير في الطرد)
        """
        if not raw_status:
            return None

        mapping = {
            # ─── حالات Yalidine الفرنسية ───
            "En attente":             "at_origin",
            "En préparation":         "at_origin",
            "En attente de collecte": "at_origin",
            "Collecté":               "in_transit",
            "En transit":             "in_transit",
            "Arrivé wilaya":          "at_destination",
            "En cours de livraison":  "out_for_delivery",
            "Sorti en livraison":     "out_for_delivery",
            "Livré":                  "delivered",
            "Tentative échouée":      "failed_attempt",
            "Retourné":               "returned",
            "Retour reçu":            "returned",
            # ─── حالات إنجليزية ───
            "pending":          "at_origin",
            "preparing":        "at_origin",
            "collected":        "in_transit",
            "in_transit":       "in_transit",
            "arrived":          "at_destination",
            "out_for_delivery": "out_for_delivery",
            "delivered":        "delivered",
            "failed":           "failed_attempt",
            "returned":         "returned",
        }

        result = mapping.get(raw_status, None)
        if result is None:
            print(f"[NORMALIZE DEBUG] حالة غير معروفة: {repr(raw_status)} — لن يتم تحديث الطرد")
        return result

    # ============================================================
    # MAGIC SYNC — جلب الطرود النشطة صفحة بصفحة
    # ============================================================
    TERMINAL_FR = {"Livré", "Retourné", "Retour reçu", "Echoué"}

    def get_active_parcels_page(self, page: int = 1, page_size: int = 50) -> tuple:
        """
        يجيب صفحة من الطرود غير المكتملة.
        يرجع: (list_of_parcels, has_more: bool)
        """
        import time
        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/parcels/",
                    headers=self._headers(),
                    params={"page_size": page_size, "page": page},
                    timeout=20
                )
                if resp.status_code == 429:
                    print(f"[YALIDINE] Rate limit — ننتظر 30 ثانية")
                    time.sleep(30)
                    continue
                if resp.status_code == 200:
                    body       = resp.json()
                    all_data   = body.get("data", [])
                    total      = body.get("total_data", 0)
                    # فلتر الطرود المكتملة
                    active     = [p for p in all_data if p.get("last_status","") not in self.TERMINAL_FR]
                    has_more   = (page * page_size) < total
                    return active, has_more
                return [], False
            except Exception as e:
                print(f"[YALIDINE] get_active_parcels_page error attempt {attempt+1}: {e}")
                time.sleep(2)
        return [], False

    # ============================================================
    # BATCH TRACK — 10 tracking numbers لكل request
    # ============================================================
    def batch_track(self, tracking_numbers: list) -> dict:
        """
        يتتبع قائمة طرود دفعة واحدة (comma-separated).
        يرجع: {tracking_number: {status, location}}
        """
        import time
        results = {}
        if not tracking_numbers:
            return results

        # Yalidine يدعم comma-separated في param tracking
        joined = ",".join(str(t) for t in tracking_numbers)

        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/parcels/",
                    headers=self._headers(),
                    params={"tracking": joined, "page_size": len(tracking_numbers)},
                    timeout=20
                )
                if resp.status_code == 429:
                    print(f"[YALIDINE BATCH] Rate limit — ننتظر 30 ثانية")
                    time.sleep(30)
                    continue
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    for p in data:
                        t          = str(p.get("tracking") or p.get("id") or "")
                        raw        = p.get("last_status") or p.get("status") or ""
                        normalized = self.normalize_status(raw)
                        if t:
                            results[t] = {
                                "status":   normalized,
                                "location": p.get("last_update_wilaya", ""),
                                "raw":      raw
                            }
                    return results
                # إذا batch ما اشتغلش → fallback فردي
                if resp.status_code == 400:
                    print(f"[YALIDINE BATCH] Batch غير مدعوم — fallback فردي")
                    return self._batch_track_individual(tracking_numbers)
                return results
            except Exception as e:
                print(f"[YALIDINE BATCH] error attempt {attempt+1}: {e}")
                time.sleep(2)
        return results

    def _batch_track_individual(self, tracking_numbers: list) -> dict:
        """Fallback: track one by one مع rate limit"""
        import time
        results = {}
        for t in tracking_numbers:
            r = self.track_parcel(str(t))
            if r and r.get("status"):
                results[str(t)] = r
            time.sleep(1.1)
        return results
