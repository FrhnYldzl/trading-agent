"""
EquityRiskAdapter — risk_manager.RiskManager'i BaseRiskManager interface'ine sarmalar.

Mevcut RiskManager class'ı tek satır değişmemiştir; bu adapter ona delege eder.
"""

from core.asset_class import AssetClass
from core.base_risk import BaseRiskManager
from risk_manager import RiskManager


class EquityRiskAdapter(BaseRiskManager):
    """BaseRiskManager → RiskManager thin adapter."""

    def __init__(self, max_risk_pct: float = None):
        self._impl = RiskManager(max_risk_pct=max_risk_pct)

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

    def dynamic_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: int = 5,
        regime: str = "neutral",
    ) -> dict:
        return self._impl.dynamic_position_size(
            equity=equity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            confidence=confidence,
            regime=regime,
        )

    def calculate_stop_loss(
        self, entry_price: float, direction: str, pct: float = 0.02
    ) -> float:
        return self._impl.calculate_stop_loss(entry_price, direction, pct)

    def calculate_take_profit(
        self,
        entry_price: float,
        direction: str,
        risk_reward: float = 2.0,
        stop_pct: float = 0.02,
    ) -> float:
        return self._impl.calculate_take_profit(
            entry_price=entry_price,
            direction=direction,
            risk_reward=risk_reward,
            stop_pct=stop_pct,
        )

    def atr_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        multiplier: float = None,
    ) -> float:
        return self._impl.atr_stop_loss(
            entry_price=entry_price, atr=atr, direction=direction, multiplier=multiplier,
        )

    def atr_take_profit(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        rr_ratio: float = 2.0,
        multiplier: float = None,
    ) -> float:
        return self._impl.atr_take_profit(
            entry_price=entry_price, atr=atr, direction=direction,
            rr_ratio=rr_ratio, multiplier=multiplier,
        )

    def check_flash_crash(self, positions: list, market_data: dict) -> dict:
        return self._impl.check_flash_crash(positions, market_data)

    def check_sector_exposure(self, equity: float, positions: list) -> dict:
        return self._impl.check_sector_exposure(equity, positions)

    def portfolio_risk_check(
        self, equity: float, positions: list, regime: str = "neutral"
    ) -> dict:
        return self._impl.portfolio_risk_check(equity, positions, regime)

    def calculate_risk_metrics(self, returns: list[float]) -> dict:
        return self._impl.calculate_risk_metrics(returns)
