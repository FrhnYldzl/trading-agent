"""
EquityBrokerAdapter — broker/equity.py'yi BaseBroker interface'ine sarmalar.

Mevcut EquityBroker class'ı tek satır değişmemiştir; bu adapter ona delege eder.
Yeni davranış eklenmez, sadece interface uyumu sağlanır.
"""

from broker.equity import EquityBroker
from core.asset_class import AssetClass
from core.base_broker import BaseBroker


class EquityBrokerAdapter(BaseBroker):
    """BaseBroker → EquityBroker thin adapter."""

    def __init__(self):
        self._impl = EquityBroker()

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

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
        return self._impl.execute(
            action=action, ticker=ticker, qty=qty, price=price,
            stop_loss=stop_loss, take_profit=take_profit, order_type=order_type,
        )

    def cancel_all_orders(self) -> dict:
        return self._impl.cancel_all_orders()

    def get_pending_orders(self) -> list:
        return self._impl.get_pending_orders()

    def emergency_liquidate(self) -> dict:
        return self._impl.emergency_liquidate()

    def get_balance(self) -> float:
        return self._impl.get_balance()

    def get_account_status(self) -> dict:
        return self._impl.get_account_status()

    def get_position(self, ticker: str) -> dict | None:
        return self._impl.get_position(ticker)
