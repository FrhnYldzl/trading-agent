"""
EquityRegimeAdapter — regime_detector.detect_regime'i BaseRegimeDetector
interface'ine sarmalar.

Mevcut detect_regime fonksiyonu pure: market_data dict in, regime dict out.
Adapter sadece interface uyumu sağlar.
"""

from core.asset_class import AssetClass
from core.base_regime import BaseRegimeDetector
from regime_detector import detect_regime


class EquityRegimeAdapter(BaseRegimeDetector):
    """BaseRegimeDetector → regime_detector.detect_regime thin adapter."""

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.EQUITY

    def detect(self, market_data: dict) -> dict:
        return detect_regime(market_data)
