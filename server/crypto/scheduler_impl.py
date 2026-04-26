"""
crypto/scheduler_impl.py — CryptoScheduler(BaseScheduler).

24/7 piyasa için adaptive frequency tablosu:

  Hafta içi (Mon-Fri)  → 30dk         (kripto orta-yoğun mod)
  Hafta sonu (Sat-Sun) → 60dk         (genelde daha yavaş hareket)

Equity scheduler'ından farklı: pre-market/after-hours/night kavramı yok.
İleride hacim-bazlı adaptive yapı eklenebilir (yüksek hacim → 15dk).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.asset_class import AssetClass
from core.base_scheduler import BaseScheduler


class CryptoScheduler(BaseScheduler):
    """24/7 sabit frequency + weekend slowdown."""

    INTERVAL_WEEKDAY_MIN = 30
    INTERVAL_WEEKEND_MIN = 60

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    def detect_scan_mode(self) -> tuple[str, int]:
        try:
            # Equity NY saatini kullanıyor; crypto için UTC mantıklı ama
            # ABD haftası kavramını korumak için NY weekday'i kullanıyoruz.
            now_ny = datetime.now(ZoneInfo("America/New_York"))
            weekday = now_ny.weekday()  # 0=Mon, 6=Sun
            if weekday >= 5:
                return ("crypto_weekend", self.INTERVAL_WEEKEND_MIN)
            return ("crypto_weekday", self.INTERVAL_WEEKDAY_MIN)
        except Exception:
            return ("crypto_fallback", 30)

    def is_active_session(self) -> bool:
        # Crypto her zaman aktif
        return True
