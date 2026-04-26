"""
core/ — Asset-class-agnostic abstract interfaces.

V5.8: Bu paket sadece interface tanımı içerir. Mevcut equity kodu (broker/equity.py,
risk_manager.py, claude_brain.py, regime_detector.py, scheduler.py) DEĞİŞTİRİLMEMİŞTİR.
equity/ paketi bu interface'leri implement eden adapter'ları içerir.

Crypto ve options modülleri ileride aynı interface'leri implement edecek.
"""

from core.asset_class import AssetClass
from core.base_broker import BaseBroker
from core.base_risk import BaseRiskManager
from core.base_brain import BaseBrain
from core.base_regime import BaseRegimeDetector
from core.base_scheduler import BaseScheduler

__all__ = [
    "AssetClass",
    "BaseBroker",
    "BaseRiskManager",
    "BaseBrain",
    "BaseRegimeDetector",
    "BaseScheduler",
]
