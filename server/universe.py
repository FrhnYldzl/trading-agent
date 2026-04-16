"""
universe.py — Broad Scan Universe Loader

NASDAQ 100 + Core WATCHLIST listesini birleştirir.
İleride S&P 500 eklenebilir (Wikipedia scraper veya Alpaca assets API ile).

Kullanım:
    from universe import get_broad_universe
    tickers = get_broad_universe()  # ['AAPL', 'MSFT', ..., 'COST', ...]

Hata durumunda: Core WATCHLIST fallback (asla boş dönmez).
"""

from typing import List


# ─────────────────────────────────────────────────────────────────
# NASDAQ 100 (2024 sonu itibarıyla güncel, ~100 sembol)
# Kaynak: Nasdaq resmi endeks üyelikleri
# Not: Liste çeyreklik güncellenir; küçük sapmalar olabilir.
# ─────────────────────────────────────────────────────────────────

NASDAQ_100: List[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "COST", "NFLX", "ASML", "AMD", "ADBE", "PEP", "CSCO",
    "TMUS", "LIN", "INTU", "TXN", "QCOM", "ISRG", "AMAT", "BKNG",
    "HON", "AMGN", "PANW", "SBUX", "ADI", "GILD", "LRCX", "MDLZ",
    "REGN", "VRTX", "KLAC", "CMCSA", "ADP", "MU", "SNPS", "INTC",
    "CDNS", "ABNB", "PYPL", "CRWD", "MAR", "ORLY", "MELI", "CTAS",
    "FTNT", "MRVL", "CSX", "PCAR", "ROP", "MNST", "WDAY", "KDP",
    "NXPI", "CHTR", "CPRT", "ADSK", "PAYX", "FANG", "KHC", "AEP",
    "EXC", "ROST", "DASH", "BKR", "IDXX", "CCEP", "FAST", "ODFL",
    "AZN", "TTD", "LULU", "GEHC", "CTSH", "EA", "DDOG", "DXCM",
    "VRSK", "MCHP", "BIIB", "ANSS", "CSGP", "CDW", "ZS", "TEAM",
    "ON", "WBD", "XEL", "ILMN", "GFS", "MDB", "TTWO", "SMCI",
    "PDD", "ARM", "APP", "PLTR", "MSTR",
]


def get_broad_universe(include_core: bool = True) -> List[str]:
    """
    Broad scan için sembol listesi döndür.

    Args:
        include_core: True ise Core WATCHLIST'i garanti ekle (duplicate'siz)

    Returns:
        Unique ticker listesi (alfabetik sıralı)

    Fallback: Hata olursa Core WATCHLIST döner (asla boş liste yok).
    """
    try:
        universe = set(NASDAQ_100)

        if include_core:
            # Circular import'u önlemek için lazy import
            from config import WATCHLIST as CORE
            universe.update(CORE)

        return sorted(universe)

    except Exception:
        # En kötü senaryo: Core WATCHLIST fallback
        try:
            from config import WATCHLIST as CORE
            return sorted(set(CORE))
        except Exception:
            # Config bile yüklenemezse minimal hardcoded fallback
            return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                    "TSLA", "META", "AMD", "SPY", "QQQ",
                    "NFLX", "CRM", "AVGO", "COIN", "MARA"]


def get_core_universe() -> List[str]:
    """
    Sadece Core WATCHLIST döndür (broad scan kapalıyken kullanılır).
    Mevcut davranışı korumak için wrapper.
    """
    try:
        from config import WATCHLIST as CORE
        return list(CORE)
    except Exception:
        return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                "TSLA", "META", "AMD", "SPY", "QQQ",
                "NFLX", "CRM", "AVGO", "COIN", "MARA"]


def universe_stats() -> dict:
    """Diagnostic: evren boyutlarını göster (dashboard/debug için)."""
    try:
        from config import WATCHLIST as CORE
        core_set = set(CORE)
        ndx_set = set(NASDAQ_100)
        broad = core_set | ndx_set

        return {
            "core_count": len(core_set),
            "nasdaq100_count": len(ndx_set),
            "broad_total": len(broad),
            "overlap": len(core_set & ndx_set),
        }
    except Exception as e:
        return {"error": str(e)}
