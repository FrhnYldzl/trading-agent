"""
base_risk.py — Abstract Risk Manager interface.

Tüm asset class'lar aynı risk felsefesini paylaşır:
  - Confidence skorundan max risk %'sine geçiş (haritası asset class'a göre kalibre)
  - ATR-based stop / take-profit
  - Sector / asset concentration limit
  - Flash crash failsafe
  - Portfolio-wide risk check (drawdown gate, max invested)

Implementasyonlar (equity / crypto / options) parametreleri farklı tutar:
  Equity:  max_risk_pct=0.02, %30 sektör limiti
  Crypto:  max_risk_pct=0.01, %40 grup limiti (L1/L2/DeFi)
  Options: max_risk_pct=0.005 premium başına, %50 underlying limiti
"""

from abc import ABC, abstractmethod

from core.asset_class import AssetClass


class BaseRiskManager(ABC):
    """
    Asset-class-agnostic risk manager interface.

    Subclass kontratı (mevcut RiskManager API'sine birebir uyar):
        asset_class             → property
        dynamic_position_size() → confidence + regime + ATR'a göre boyut
        calculate_stop_loss()   → entry'den fiyat türeti
        calculate_take_profit() → R-multiple bazlı
        atr_stop_loss/atr_take_profit → ATR'a duyarlı
        check_flash_crash()     → günlük büyük düşüş tespiti
        check_sector_exposure() → sektör/grup yoğunluk kontrolü
        portfolio_risk_check()  → cüzdan-genel sağlık
        calculate_risk_metrics() → Sharpe, VaR, MaxDD
    """

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass:
        ...

    @abstractmethod
    def dynamic_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: int = 5,
        regime: str = "neutral",
    ) -> dict:
        """
        Pozisyon boyutu hesapla.
        Returns: {"qty": float, "risk_amount": float, "risk_pct": float, ...}
        """
        ...

    @abstractmethod
    def calculate_stop_loss(
        self, entry_price: float, direction: str, pct: float = 0.02
    ) -> float:
        ...

    @abstractmethod
    def calculate_take_profit(
        self,
        entry_price: float,
        direction: str,
        risk_reward: float = 2.0,
        stop_pct: float = 0.02,
    ) -> float:
        ...

    @abstractmethod
    def atr_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        multiplier: float = None,
    ) -> float:
        ...

    @abstractmethod
    def atr_take_profit(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        rr_ratio: float = 2.0,
        multiplier: float = None,
    ) -> float:
        ...

    @abstractmethod
    def check_flash_crash(self, positions: list, market_data: dict) -> dict:
        """Returns: {"trigger": bool, "affected": [...], "reason": "..."}"""
        ...

    @abstractmethod
    def check_sector_exposure(self, equity: float, positions: list) -> dict:
        """Returns: {"by_sector": {"Tech": 35.2, ...}, "violations": [...]}"""
        ...

    @abstractmethod
    def portfolio_risk_check(
        self, equity: float, positions: list, regime: str = "neutral"
    ) -> dict:
        """Returns: {"healthy": bool, "warnings": [...], "max_invested_pct": ...}"""
        ...

    @abstractmethod
    def calculate_risk_metrics(self, returns: list[float]) -> dict:
        """Returns: {"sharpe": ..., "var_95": ..., "max_drawdown": ..., "volatility": ...}"""
        ...
