"""
crypto/ — Crypto asset class implementation.

V5.9'da eklendi. Equity ile aynı abstract interface'leri (core/ paketi) implement
eder, ama içerik kripto piyasasına özgüdür:

  - 24/7 piyasa (kapanış yok, weekend yok)
  - Yüksek volatilite (BTC günlük ATR ~%3-5, hisseden 2-3x)
  - PDT kuralı yok, instant settlement
  - Ondalıklı pozisyon (0.0001 BTC alabilirsin)
  - BTC dominance + alt-coin korelasyonu rejim için kritik
  - Stablecoin'ler (USDC/USDT/USDG) momentum stratejisinden hariç

Equity modülünden hiçbir şey değiştirilmez. Equity ve crypto aynı broker
hesabını paylaşır (Alpaca tek hesap), ama farklı endpoint'leri çağırır.
"""

# Şu an sadece foundation: universe + data layer.
# Broker / scheduler / risk / regime / brain implementasyonları sıradaki commit'te.

from crypto.universe import (
    CRYPTO_CORE,
    CRYPTO_EXTENDED,
    STABLECOINS,
    get_crypto_core_universe,
    get_crypto_broad_universe,
    is_stablecoin,
    crypto_universe_stats,
)

__all__ = [
    "CRYPTO_CORE",
    "CRYPTO_EXTENDED",
    "STABLECOINS",
    "get_crypto_core_universe",
    "get_crypto_broad_universe",
    "is_stablecoin",
    "crypto_universe_stats",
]
