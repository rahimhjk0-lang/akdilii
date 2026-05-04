"""
YalidineCarrier — Self-Aware Rate Limiter
==========================================
Rate Limits (Yalidine Docs):
  - 5  req / second
  - 50 req / minute
  - 1000 req / hour

Headers monitored after every call:
  x-second-quota-left  → إذا < 1 → sleep 1.2s
  x-minute-quota-left  → إذا < 5 → sleep 65s
  Retry-After          → عند 429 → sleep بالقيمة
"""

import time
import logging
import requests
from carriers import BaseCarrier

logger = logging.getLogger("akdili-yalidine")

# ─── ثوابت Rate Limit ───────────────────────────────────────
SEC_QUOTA_SAFE   = 1    # إذا تبقّى أقل من 1 req/sec  → sleep
MIN_QUOTA_SAFE   = 5    # إذا تبقّى أقل من 5 req/min  → sleep طويل
SEC_SLEEP        = 1.2  # نوم بين الطلبات (أقل من 5 req/sec)
MIN_SLEEP        = 65.0 # نوم عند نفاد الـ minute quota
BACKOFF_429      = 30.0 # نوم عند 429 إذا ما فيش Retry-After
MAX_RETRIES      = 3    # محاولات قبل الاستسلام

# حالات Yalidine المكتملة — ما نستوردهاش
TERMINAL_FR = {"Livré", "Retourné", "Retour reçu", "Echoué"}


# ============================================================
# QuotaGuard — يراقب كل response ويقرر متى ننام
# ============================================================
class QuotaGuard:
    """
    يقرأ headers كل response ويطبّق Sleep الصحيح.
    Shared state داخل نفس الـ carrier instance.
    """
    def __init__(self):
        self.sec_left = 5     # نبدأ بتقدير آمن
        self.min_left = 50
        self.hour_left = 1000

    def absorb(self, resp: requests.Response):
        """يقرأ headers الـ response ويحدّث الـ quota state."""
        try:
            self.sec_left  = int(resp.headers.get("x-second-quota-left",  self.sec_left))
            self.min_left  = int(resp.headers.get("x-minute-quota-left",  self.min_left))
            self.hour_left = int(resp.headers.get("x-hour-quota-left",    self.hour_left))
        except (ValueError, TypeError):
            pass  # headers غير موجودة أو غير صحيحة — نحافظ على القيم السابقة

        logger.debug(
            f"[QUOTA] sec={self.sec_left} | min={self.min_left} | hour={self.hour_left}"
        )

    def throttle(self):
        """
        يُنفَّذ بعد كل request ناجح.
        يحسب الـ sleep المطلوب بناءً على الـ quota المتبقي.
        """
        # ── حالة حرجة: minute quota شبه نافد ──
        if self.min_left < MIN_QUOTA_SAFE:
            logger.warning(
                f"[QUOTA] ⚠️ minute quota={self.min_left} < {MIN_QUOTA_SAFE} "
                f"— ننام {MIN_SLEEP}s"
            )
            time.sleep(MIN_SLEEP)
            return

        # ── حالة عادية: نحافظ على 5 req/sec ──
        if self.sec_left < SEC_QUOTA_SAFE:
            logger.debug(f"[QUOTA] sec quota={self.sec_left} — ننام {SEC_SLEEP}s")
            time.sleep(SEC_SLEEP)
        else:
            # دائماً sleep أدنى بين الطلبات (200ms) لتجنب burst
            time.sleep(0.22)

    def handle_429(self, resp: requests.Response):
        """يقرأ Retry-After وينام."""
        retry_after = resp.headers.get("Retry-After")
        sleep_secs  = float(retry_after) if retry_after else BACKOFF_429
        logger.warning(f"[QUOTA] 429 — Retry-After={retry_after} — ننام {sleep_secs}s")
        time.sleep(sleep_secs)


# ============================================================
# YalidineCarrier
# ============================================================
class YalidineCarrier(BaseCarrier):

    CARRIER_CODE = "yalidine"
    CARRIER_NAME = "Yalidine Express"
    BASE_URL     = "https://api.yalidine.app/v1"

    def __init__(self, api_key: str, api_id: str = ""):
        super().__init__(api_key)
        self.api_id = api_id
        self.quota  = QuotaGuard()   # ← واحد لكل instance

    # ────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {
            "X-API-ID":     self.api_id,
            "X-API-TOKEN":  self.api_key,
            "Content-Type": "application/json",
        }

    # ============================================================
    # _safe_get — الدالة الوحيدة التي تستدعي requests.get
    # كل دوال الـ carrier تمر من هنا
    # ============================================================
    def _safe_get(self, endpoint: str, params: dict = None) -> requests.Response | None:
        """
        يرسل GET request مع:
        - Retry تلقائي (MAX_RETRIES)
        - 429 backoff (Retry-After أو 30s)
        - Header-based throttle بعد كل نجاح
        """
        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self._headers(),
                    params=params or {},
                    timeout=25,
                )

                # ── 429: نوم ثم retry ──
                if resp.status_code == 429:
                    self.quota.handle_429(resp)
                    continue

                # ── نجاح: اقرأ headers + throttle ──
                if resp.status_code == 200:
                    self.quota.absorb(resp)
                    self.quota.throttle()
                    return resp

                # ── أخطاء أخرى: لا retry ──
                logger.warning(f"[YALIDINE] {endpoint} HTTP {resp.status_code}")
                return resp

            except requests.exceptions.Timeout:
                logger.warning(f"[YALIDINE] Timeout attempt {attempt}/{MAX_RETRIES}")
                time.sleep(2 * attempt)
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"[YALIDINE] ConnectionError attempt {attempt}: {e}")
                time.sleep(3 * attempt)
            except Exception as e:
                logger.error(f"[YALIDINE] Unexpected error: {e}")
                break

        logger.error(f"[YALIDINE] {endpoint} — فشل بعد {MAX_RETRIES} محاولات")
        return None

    # ============================================================
    # login_and_get_key — التحقق من صحة المفاتيح
    # ============================================================
    def login_and_get_key(self, email: str, password: str) -> dict:
        api_id    = email.strip()
        api_token = password.strip()

        if not api_id or not api_token:
            return {"success": False, "error": "أدخل API ID و API Token"}

        # نستعمل instance مؤقتة للتحقق
        temp = YalidineCarrier(api_key=api_token, api_id=api_id)
        resp = temp._safe_get("/parcels/", {"page_size": 1, "page": 1})

        if resp is None:
            return {"success": False, "error": "لا استجابة من Yalidine — تحقق من اتصالك"}
        if resp.status_code == 401:
            return {"success": False, "error": "API ID أو Token غلط — تحقق من لوحة Yalidine"}
        if resp.status_code in [200, 404]:
            return {"success": True, "api_id": api_id, "api_token": api_token}

        return {"success": True, "api_id": api_id, "api_token": api_token}

    # ============================================================
    # get_parcels — قائمة بسيطة (صفحة واحدة)
    # ============================================================
    def get_parcels(self) -> list:
        resp = self._safe_get("/parcels/", {"page_size": 50, "page": 1})
        if resp and resp.status_code == 200:
            return resp.json().get("data", [])
        return []

    # ============================================================
    # track_parcel — تتبع طرد واحد
    # ============================================================
    def track_parcel(self, tracking_number: str) -> dict:
        resp = self._safe_get(f"/parcels/{tracking_number}/")

        if resp is None or resp.status_code != 200:
            code = resp.status_code if resp else "N/A"
            logger.debug(f"[YALIDINE] track {tracking_number} → HTTP {code}")
            return {}

        data       = resp.json()
        raw_status = data.get("last_status") or data.get("status") or ""

        logger.debug(
            f"[YALIDINE] {tracking_number} | "
            f"last_status={repr(data.get('last_status'))} | "
            f"status={repr(data.get('status'))} | "
            f"used={repr(raw_status)}"
        )

        if not raw_status:
            return {
                "tracking_number": tracking_number,
                "status":   None,
                "location": data.get("last_update_wilaya", ""),
                "raw":      data,
            }

        normalized = self.normalize_status(raw_status)
        return {
            "tracking_number": tracking_number,
            "status":   normalized,   # None إذا حالة مجهولة
            "location": data.get("last_update_wilaya", ""),
            "raw":      data,
        }

    # ============================================================
    # get_active_parcels_page — صفحة بصفحة للـ Initial Sync
    # ============================================================
    def get_active_parcels_page(self, page: int = 1, page_size: int = 50) -> tuple:
        """
        يجيب صفحة من الطرود غير المكتملة.
        يرجع: (list_of_active_parcels, has_more: bool)
        _safe_get يتكفل بالـ rate limiting.
        """
        resp = self._safe_get("/parcels/", {"page_size": page_size, "page": page})

        if resp is None or resp.status_code != 200:
            return [], False

        body     = resp.json()
        all_data = body.get("data", [])
        total    = body.get("total_data", len(all_data))
        active   = [p for p in all_data if p.get("last_status", "") not in TERMINAL_FR]
        has_more = (page * page_size) < total

        logger.info(
            f"[YALIDINE] صفحة {page} — "
            f"مجموع:{total} | هذي الصفحة:{len(all_data)} | نشط:{len(active)} | "
            f"quota_min={self.quota.min_left}"
        )
        return active, has_more

    # ============================================================
    # batch_track — 10 tracking numbers لكل request
    # ============================================================
    def batch_track(self, tracking_numbers: list) -> dict:
        """
        يتتبع دفعة (comma-separated) مع header-aware throttle.
        يرجع: {tracking_number: {status, location, raw}}
        """
        results = {}
        if not tracking_numbers:
            return results

        joined = ",".join(str(t) for t in tracking_numbers)
        resp   = self._safe_get(
            "/parcels/",
            {"tracking": joined, "page_size": len(tracking_numbers)},
        )

        if resp is None:
            logger.warning("[YALIDINE BATCH] لا استجابة — fallback فردي")
            return self._batch_track_individual(tracking_numbers)

        if resp.status_code == 400:
            logger.warning("[YALIDINE BATCH] Batch غير مدعوم — fallback فردي")
            return self._batch_track_individual(tracking_numbers)

        if resp.status_code != 200:
            return results

        for p in resp.json().get("data", []):
            t          = str(p.get("tracking") or p.get("id") or "")
            raw        = p.get("last_status") or p.get("status") or ""
            normalized = self.normalize_status(raw)
            if t:
                results[t] = {
                    "status":   normalized,
                    "location": p.get("last_update_wilaya", ""),
                    "raw":      raw,
                }

        logger.info(
            f"[YALIDINE BATCH] {len(tracking_numbers)} tracking → "
            f"{len(results)} نتيجة | quota_min={self.quota.min_left}"
        )
        return results

    def _batch_track_individual(self, tracking_numbers: list) -> dict:
        """Fallback: track واحد بواحد — _safe_get يتكفل بالـ throttle."""
        results = {}
        for t in tracking_numbers:
            r = self.track_parcel(str(t))
            if r and r.get("status"):
                results[str(t)] = r
        return results

    # ============================================================
    # normalize_status — mapping صارم بلا fallback
    # ============================================================
    def normalize_status(self, raw_status: str):
        """
        حالة مجهولة → None (لا تغيير في الطرد)
        """
        if not raw_status:
            return None

        mapping = {
            # ─── فرنسية (Yalidine) ───
            "En attente":             "at_origin",
            "En préparation":         "at_origin",
            "En attente de collecte": "at_origin",
            "Collecté":               "in_transit",
            "En transit":             "in_transit",
            "Vers Wilaya":            "in_transit",
            "Arrivé wilaya":          "at_destination",
            "En cours de livraison":  "out_for_delivery",
            "Sorti en livraison":     "out_for_delivery",
            "Livré":                  "delivered",
            "Tentative échouée":      "failed_attempt",
            "Retourné":               "returned",
            "Retour reçu":            "returned",
            "Retourné au vendeur":    "returned",
            "Retour à retirer":       "returned",
            # ─── إنجليزية ───
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

        result = mapping.get(raw_status)
        if result is None:
            logger.warning(f"[NORMALIZE] حالة غير معروفة: {repr(raw_status)}")
        return result
