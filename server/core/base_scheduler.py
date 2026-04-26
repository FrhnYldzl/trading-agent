"""
base_scheduler.py — Abstract Scheduler interface.

V5.6 adaptive schedule felsefesi her asset class için aynı: market mode'a göre
sıklık değişir. Ama mode tanımları ve tablo farklı:

  Equity (V5.6):
    market_open      (9:30-16 ET)  → 5dk
    pre_market        (4-9:30 ET)  → 15dk
    after_hours      (16-20 ET)   → 30dk
    night            (20-4 ET)    → 60dk
    weekend                       → 180dk

  Crypto:
    24/7 sabit                    → 30dk (ya da hacme göre adaptive)
    weekend slowdown opsiyonel    → 60dk

  Options:
    Equity gibi + expirasyon yakınında theta urgency
    expiring_today                → 5dk (delta-hedge urgency)
"""

from abc import ABC, abstractmethod

from core.asset_class import AssetClass


class BaseScheduler(ABC):
    """
    Asset-class-agnostic scheduler interface.

    Subclass kontratı:
        asset_class       → property
        detect_scan_mode() → (mode_name, interval_min)
        is_active_session() → o anda piyasa açık mı? (24/7 ise hep True)
    """

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass:
        ...

    @abstractmethod
    def detect_scan_mode(self) -> tuple[str, int]:
        """
        O anki tarama modunu ve dakika cinsinden interval'ı dön.

        Returns: ("market_open", 5) gibi.
        """
        ...

    @abstractmethod
    def is_active_session(self) -> bool:
        """Piyasa şu anda işlem yapılabilir durumda mı?"""
        ...
