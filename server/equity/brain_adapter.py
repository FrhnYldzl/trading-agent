"""
EquityBrainAdapter — claude_brain modülünü BaseBrain interface'ine sarmalar.

Mevcut claude_brain fonksiyonları (run_brain, review_past_trades) tek satır
değişmemiştir; bu adapter onları çağırır. Interface'in regime/sentiment/
learning_context parametreleri equity adapter'da KULLANILMAZ — mevcut
run_brain bu bilgileri ya kendi içinde alıyor ya gerek duymuyor. Crypto/options
adapter'ları bu parametreleri prompt'a enjekte etmek için kullanacak.
"""

from claude_brain import run_brain, review_past_trades
from core.asset_class import AssetClass
from core.base_brain import BaseBrain


class EquityBrainAdapter(BaseBrain):
    """BaseBrain → claude_brain (functional) thin adapter."""

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

    def run_brain(
        self,
        market_data: dict,
        portfolio: dict,
        recent_trades: list = None,
        regime: dict = None,           # mevcut equity impl tarafından kullanılmıyor
        sentiment: dict = None,        # mevcut equity impl tarafından kullanılmıyor
        learning_context: str = None,  # mevcut equity impl tarafından kullanılmıyor
    ) -> dict:
        # NOT: mevcut equity run_brain'in sadece (market_data, portfolio,
        # recent_trades, auto_execute) parametreleri var. auto_execute scheduler
        # tarafında zaten dispatch sırasında veriliyor; adapter buna karışmaz.
        return run_brain(
            market_data=market_data,
            portfolio=portfolio,
            recent_trades=recent_trades or [],
        )

    def review_past_trades(self, recent_trades: list, portfolio: dict) -> dict:
        return review_past_trades(recent_trades=recent_trades, portfolio=portfolio)
