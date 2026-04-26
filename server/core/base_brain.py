"""
base_brain.py — Abstract AI Brain interface.

Multi-step reasoning iskeleti her asset class için aynı; prompt içeriği farklı:
  Equity:  Trend + momentum + breadth + sektör rotasyonu
  Crypto:  BTC dominance, funding rate, on-chain (varsa), 24/7 bağlam
  Options: Greeks (delta/gamma/theta/vega), IV rank, term structure, expirasyon

Gemini audit kancası burada implementasyondan bağımsız (gemini_auditor modülü
kararı asset-class'tan habersiz işler).
"""

from abc import ABC, abstractmethod

from core.asset_class import AssetClass


class BaseBrain(ABC):
    """
    Asset-class-agnostic AI brain interface.

    Subclass kontratı:
        asset_class    → property
        run_brain()    → market_data + portfolio + history → karar dict
        review_past_trades() → geçmiş işlemleri analiz et, ders çıkar
    """

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass:
        ...

    @abstractmethod
    def run_brain(
        self,
        market_data: dict,
        portfolio: dict,
        recent_trades: list = None,
        regime: dict = None,
        sentiment: dict = None,
        learning_context: str = None,
    ) -> dict:
        """
        Tek tarama döngüsü için AI kararı üret.

        Returns:
            {
              "regime": "bull|bear|...",
              "strategy": "momentum|mean_reversion|...",
              "decisions": [
                {"action": "long|short|close|hold", "ticker": ..., "confidence": int,
                 "reasoning": "...", "stop_loss": float, "take_profit": float},
                ...
              ],
              "meta": {...}
            }
        """
        ...

    @abstractmethod
    def review_past_trades(self, recent_trades: list, portfolio: dict) -> dict:
        """
        Geçmiş işlemleri analiz et — ders, journal entry, prompt iyileştirme önerisi.
        Returns: {"lessons": [...], "performance": {...}, "suggestions": [...]}
        """
        ...
