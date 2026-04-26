"""
EquitySchedulerAdapter — scheduler.py'deki V5.6 adaptive mod tespitini
BaseScheduler interface'ine sarmalar.

scheduler.py'nin orkestrasyon kısmı (smart_scan_dispatcher, run_scan, start)
DOKUNULMUYOR. Bu adapter sadece mod tespit + market saati sorularını
interface'e açar. Crypto/options adapter'ları kendi mode tablolarını
implement edecek.
"""

from core.asset_class import AssetClass
from core.base_scheduler import BaseScheduler
from market_scanner import is_market_open, is_premarket
from scheduler import _detect_scan_mode


class EquitySchedulerAdapter(BaseScheduler):
    """BaseScheduler → V5.6 equity scheduler thin adapter."""

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

    def detect_scan_mode(self) -> tuple[str, int]:
        return _detect_scan_mode()

    def is_active_session(self) -> bool:
        """
        Equity için "aktif session" = market açık VEYA pre-market.
        After-hours işlem yapılamadığı için aktif sayılmaz.
        """
        try:
            return bool(is_market_open() or is_premarket())
        except Exception:
            return False
