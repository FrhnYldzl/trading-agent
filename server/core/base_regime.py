"""
base_regime.py — Abstract Regime Detector interface.

Kantitatif rejim algılaması her asset class için aynı bileşenleri kullanır:
  volatility / trend / momentum / breadth → kompozit skor → rejim etiketi

Ama bileşenlerin hesaplanışı farklı:
  Equity:  SPY benchmark, watchlist breadth (advancing/declining), EMA50
  Crypto:  BTC benchmark, top-N market-cap breadth, BTC dominance trendi
  Options: IV rank (%volatility), term structure (trend), put/call ratio (momentum)
"""

from abc import ABC, abstractmethod

from core.asset_class import AssetClass


class BaseRegimeDetector(ABC):
    """
    Asset-class-agnostic regime detector interface.

    Subclass kontratı:
        asset_class    → property
        detect()       → market_data → regime dict
    """

    @property
    @abstractmethod
    def asset_class(self) -> AssetClass:
        ...

    @abstractmethod
    def detect(self, market_data: dict) -> dict:
        """
        Mevcut rejimi tespit et.

        Returns:
            {
              "regime": "bull_strong|bull|neutral|bear|bear_strong",
              "quant_score": float,        # 0-100
              "confidence": int,           # 0-100
              "components": {
                "volatility": {"score": ..., "label": "low|elevated|high"},
                "trend":      {"score": ..., "label": "bullish|sideways|bearish"},
                "momentum":   {"score": ..., "label": "weak|moderate|strong"},
                "breadth":    {"score": ..., "label": "narrow|broad|strong"},
              },
              "reasoning": "...",
              "timestamp": ISO8601 string,
            }
        """
        ...
