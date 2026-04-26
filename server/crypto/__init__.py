"""
crypto/ — Crypto asset class implementation.

V5.9'da eklendi. Equity ile aynı abstract interface'leri (core/ paketi) implement
eder, ama içerik kripto piyasasına özgüdür:

  - 24/7 piyasa
  - Yüksek volatilite (BTC günlük ATR ~%3-5, hisseden 2-3x)
  - PDT kuralı yok, instant settlement
  - Ondalıklı pozisyon
  - BTC dominance + alt-coin korelasyonu rejim için kritik
  - Stablecoin'ler (USDC/USDT/USDG) momentum stratejisinden hariç

Equity modülünden hiçbir şey değiştirilmez. Equity ve crypto aynı broker
hesabını paylaşır (Alpaca tek hesap), ama farklı endpoint/sembol formatı.
"""

from crypto.universe import (
    CRYPTO_CORE,
    CRYPTO_EXTENDED,
    STABLECOINS,
    get_crypto_core_universe,
    get_crypto_broad_universe,
    is_stablecoin,
    crypto_universe_stats,
)
from crypto.data import get_crypto_data
from crypto.broker_impl import CryptoBroker
from crypto.risk_impl import CryptoRiskManager, get_asset_group, CRYPTO_ASSET_GROUP
from crypto.scheduler_impl import CryptoScheduler
from crypto.regime_impl import CryptoRegimeDetector
from crypto.brain_impl import CryptoBrain
from crypto.auto_executor import CryptoAutoExecutor
from crypto.journal import CryptoJournal

__all__ = [
    # Universe
    "CRYPTO_CORE", "CRYPTO_EXTENDED", "STABLECOINS",
    "get_crypto_core_universe", "get_crypto_broad_universe",
    "is_stablecoin", "crypto_universe_stats",
    # Data
    "get_crypto_data",
    # Implementations
    "CryptoBroker", "CryptoRiskManager", "CryptoScheduler",
    "CryptoRegimeDetector", "CryptoBrain",
    # Auto execution + journal
    "CryptoAutoExecutor", "CryptoJournal",
    # Risk groups
    "get_asset_group", "CRYPTO_ASSET_GROUP",
]
