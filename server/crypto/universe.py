"""
crypto/universe.py — Crypto asset universe.

Equity'deki universe.py'nin (NDX 100 + Core 15) kripto karşılığı.

İki katman:
  CRYPTO_CORE     — Mavi-çip, en yüksek hacim/likidite (10 sembol)
  CRYPTO_EXTENDED — Tradable her şey (~33 sembol, stablecoin'ler hariç)

Stablecoin'ler (USDC, USDT, USDG) momentum tarama için anlamsız —
fiyat değişimi neredeyse sıfırdır. Universe'lere DAHİL EDİLMEZ.

Sembol formatı: Alpaca'nın kullandığı slash-separated quote pair:
    "BTC/USD" (NOT "BTCUSD")

Veri kaynağı: Alpaca Trading API → get_all_assets(asset_class=CRYPTO).
Bu liste 19 Nisan 2026'da Alpaca'dan canlı çekilmiştir; çeyreklik
güncellenmesi önerilir (yeni listing'ler için crypto_universe_stats()
ile karşılaştır).
"""

from typing import List


# ─────────────────────────────────────────────────────────────────
# Stablecoin'ler — momentum stratejisinden HARİÇ
# ─────────────────────────────────────────────────────────────────
STABLECOINS: List[str] = ["USDC/USD", "USDT/USD", "USDG/USD"]


# ─────────────────────────────────────────────────────────────────
# Crypto Core — Mavi-çip, ana takip listesi
# Ekleme kriteri: piyasa değeri top 15, Alpaca'da listed, USD çifti var
# ─────────────────────────────────────────────────────────────────
CRYPTO_CORE: List[str] = [
    "BTC/USD",   # Bitcoin — anchor / benchmark
    "ETH/USD",   # Ethereum — L1 #2
    "SOL/USD",   # Solana — L1 yüksek perf
    "XRP/USD",   # Ripple — payments
    "DOGE/USD",  # Dogecoin — meme/retail
    "ADA/USD",   # Cardano — L1
    "AVAX/USD",  # Avalanche — L1
    "LINK/USD",  # Chainlink — oracle
    "DOT/USD",   # Polkadot — L0
    "LTC/USD",   # Litecoin — eski PoW
]


# ─────────────────────────────────────────────────────────────────
# Crypto Extended — Alpaca'da tradable tüm USD çiftleri (Core dahil,
# stablecoin'ler hariç). Broad scan için bu liste kullanılır.
# ─────────────────────────────────────────────────────────────────
CRYPTO_EXTENDED: List[str] = [
    # L1 / L2 / Smart contract platformları
    "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD",
    "DOT/USD", "ARB/USD", "POL/USD", "XTZ/USD", "FIL/USD",
    # Payment & store of value
    "XRP/USD", "LTC/USD", "BCH/USD",
    # DeFi blue-chip
    "UNI/USD", "AAVE/USD", "CRV/USD", "SUSHI/USD", "YFI/USD",
    "LDO/USD", "SKY/USD",
    # Oracle / infra
    "LINK/USD", "GRT/USD", "RENDER/USD",
    # Meme / sentiment-driven
    "DOGE/USD", "SHIB/USD", "PEPE/USD", "BONK/USD", "WIF/USD",
    "TRUMP/USD", "HYPE/USD",
    # Real-world asset / specialty
    "PAXG/USD",  # Tokenized gold
    "ONDO/USD",  # RWA/treasury
    # Utility
    "BAT/USD",   # Brave attention token
]


def get_crypto_core_universe() -> List[str]:
    """Sadece Core 10 — broad scan kapalıyken kullanılır."""
    return list(CRYPTO_CORE)


def get_crypto_broad_universe(include_core: bool = True) -> List[str]:
    """
    Broad scan için tüm tradable kripto sembolleri (stablecoin'ler hariç).

    Args:
        include_core: True ise Core garanti dahil (zaten EXTENDED içinde).

    Returns:
        Unique sembol listesi (alfabetik). Hata olursa Core fallback.
    """
    try:
        universe = set(CRYPTO_EXTENDED)
        if include_core:
            universe.update(CRYPTO_CORE)
        # Stablecoin'leri kesinlikle hariç tut
        universe -= set(STABLECOINS)
        return sorted(universe)
    except Exception:
        return sorted(set(CRYPTO_CORE) - set(STABLECOINS))


def is_stablecoin(symbol: str) -> bool:
    """Sembol stablecoin mi? Momentum hesabında atlanır."""
    return symbol.upper() in STABLECOINS


def crypto_universe_stats() -> dict:
    """Diagnostic: evren boyutları (dashboard / testing için)."""
    core_set = set(CRYPTO_CORE)
    ext_set = set(CRYPTO_EXTENDED)
    stable_set = set(STABLECOINS)
    broad = (core_set | ext_set) - stable_set

    return {
        "core_count": len(core_set),
        "extended_count": len(ext_set),
        "stablecoin_count": len(stable_set),
        "broad_total": len(broad),
        "core_in_extended": len(core_set & ext_set),  # ideal: 10
    }
