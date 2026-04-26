"""
equity/ — Equity asset class adapter package.

Mevcut equity modüllerini (broker/equity.py, risk_manager.py, claude_brain.py,
regime_detector.py, scheduler.py) core/ paketindeki abstract interface'lere
sarmalar. Mevcut modüller HİÇ DEĞİŞTİRİLMEMİŞTİR.

Refactor stratejisi: thin adapter / facade pattern.
Her adapter mevcut implementasyonu instance olarak tutar veya direkt fonksiyon
çağrısı yapar; ek bir davranış eklemez. Crypto/options paketleri ileride aynı
interface'i kendileri için sıfırdan implement edecek.
"""

from equity.broker_adapter import EquityBrokerAdapter
from equity.risk_adapter import EquityRiskAdapter
from equity.brain_adapter import EquityBrainAdapter
from equity.regime_adapter import EquityRegimeAdapter
from equity.scheduler_adapter import EquitySchedulerAdapter

__all__ = [
    "EquityBrokerAdapter",
    "EquityRiskAdapter",
    "EquityBrainAdapter",
    "EquityRegimeAdapter",
    "EquitySchedulerAdapter",
]
