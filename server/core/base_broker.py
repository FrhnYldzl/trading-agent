"""
base_broker.py — Abstract Broker interface.

Tüm asset class'ların broker implementasyonları bu interface'i izler.
Equity (paper/live) için EquityBrokerAdapter, ileride crypto için CryptoBroker,
options için OptionsBroker bu sınıfı implement eder.

Tasarım kuralı:
- Public surface küçük ve net olmalı (execute, get_position, get_balance, ...)
- Asset-class-specific detaylar (PDT, expirasyon, leverage) implementasyonun
  kendi sorumluluğu — interface bunlardan bahsetmez.
- Hata durumunda exception fırlatılmaz; dict döner: {"status": "error|rejected|...", ...}
  Mevcut equity koduyla geriye uyumluluk için bu sözleşme korunur.
"""

from abc import ABC, abstractmethod

from core.asset_class import AssetClass


class BaseBroker(ABC):
    """
    Asset-class-agnostic broker interface.

    Subclass kontratı:
        asset_class    → AssetClass property
        execute()      → emir gönder, dict dön
        cancel_all_orders() → bekleyen tüm emirleri iptal et
        get_pending_orders() → bekleyen emir listesi
        emergency_liquidate() → tüm pozisyonları piyasada kapa
        get_balance()  → hesap bakiyesi (USD)
        get_account_status() → hesap durumu dict
        get_position() → tek sembol için pozisyon, yoksa None
    """

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass:
        """Bu broker hangi asset class'ı yönetir?"""
        ...

    @abstractmethod
    def execute(
        self,
        action: str,
        ticker: str,
        qty: float,
        price: float,
        stop_loss: float = None,
        take_profit: float = None,
        order_type: str = "market",
    ) -> dict:
        """
        Emir gönder.

        action: "long", "short", "close_long", "close_short" (asset class
                bunlardan farklı bir alt küme destekleyebilir; uyumsuz aksiyonu
                reject ile dön).
        Returns: {"status": "filled|pending|rejected|error", "ticker": ..., ...}
        """
        ...

    @abstractmethod
    def cancel_all_orders(self) -> dict:
        """Bekleyen emirleri iptal et. Returns: {"cancelled": int, ...}"""
        ...

    @abstractmethod
    def get_pending_orders(self) -> list:
        """Bekleyen emirler listesi (dict listesi)."""
        ...

    @abstractmethod
    def emergency_liquidate(self) -> dict:
        """
        Tüm pozisyonları piyasa fiyatından kapa (acil durum).
        Bracket / OCO emirleri de iptal edilir.
        """
        ...

    @abstractmethod
    def get_balance(self) -> float:
        """Hesap bakiyesi (USD)."""
        ...

    @abstractmethod
    def get_account_status(self) -> dict:
        """Hesap meta bilgisi: bakiye, equity, buying_power, restrict, vs."""
        ...

    @abstractmethod
    def get_position(self, ticker: str) -> dict | None:
        """Sembol için açık pozisyon (qty, avg_entry, market_value, ...) ya da None."""
        ...
