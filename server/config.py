"""
config.py — Merkezi Konfigürasyon Motoru (V3)

Tüm parametreler tek merkezden yönetilir.
Öncelik sırası: Environment Variable > config.json > varsayılan değer
"""

import json
import os
from pathlib import Path


_CONFIG_PATH = Path(__file__).parent / "config.json"
_file_config: dict = {}

if _CONFIG_PATH.exists():
    with open(_CONFIG_PATH, "r") as f:
        _file_config = json.load(f)


def _get(key: str, default=None, cast=None):
    """Env > config.json > default sırasıyla değer al."""
    val = os.getenv(key) or _file_config.get(key, default)
    if val is None:
        return default
    if cast:
        try:
            return cast(val)
        except (ValueError, TypeError):
            return default
    return val


# ═══════════════════════════════════════════════════════════════
# GENEL
# ═══════════════════════════════════════════════════════════════

PORT = _get("PORT", 8000, int)
WEBHOOK_SECRET = _get("WEBHOOK_SECRET", "")
AI_MODEL = _get("AI_MODEL", "claude-sonnet-4-6")

# ═══════════════════════════════════════════════════════════════
# RİSK YÖNETİMİ
# ═══════════════════════════════════════════════════════════════

MAX_RISK_PCT = _get("MAX_RISK_PCT", 0.02, float)
MAX_POSITION_PCT = _get("MAX_POSITION_PCT", 0.15, float)         # Tek pozisyon max portföy %'si
MAX_SECTOR_PCT = _get("MAX_SECTOR_PCT", 0.40, float)             # Tek sektör max portföy %'si
ATR_MULTIPLIER = _get("ATR_MULTIPLIER", 1.5, float)              # ATR stop-loss çarpanı
ORDER_COOLDOWN_SEC = _get("ORDER_COOLDOWN_SEC", 60, int)         # Aynı ticker emir bekleme süresi
FLASH_CRASH_THRESHOLD = _get("FLASH_CRASH_THRESHOLD", 0.05, float)  # %5 anlık düşüş = failsafe

# Güven skoru → risk yüzdesi haritası
CONFIDENCE_RISK_MAP = _file_config.get("CONFIDENCE_RISK_MAP", {
    "10": 0.020, "9": 0.020, "8": 0.018, "7": 0.015,
    "6": 0.012, "5": 0.010, "4": 0.008,
    "3": 0.000, "2": 0.000, "1": 0.000,
})

# Rejim → risk çarpanı haritası
REGIME_MULTIPLIERS = _file_config.get("REGIME_MULTIPLIERS", {
    "bull_strong": 1.0, "bull": 0.9, "neutral": 0.7,
    "bear": 0.5, "bear_strong": 0.3,
})

# Rejim → max yatırım yüzdesi
REGIME_MAX_INVESTED = _file_config.get("REGIME_MAX_INVESTED", {
    "bull_strong": 95, "bull": 85, "neutral": 70,
    "bear": 40, "bear_strong": 30,
})

# ═══════════════════════════════════════════════════════════════
# PİYASA TARAMA
# ═══════════════════════════════════════════════════════════════

WATCHLIST = _file_config.get("WATCHLIST", [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "TSLA", "META", "AMD", "SPY", "QQQ",
    "NFLX", "CRM", "AVGO", "COIN", "MARA",
])

BENCHMARK = _get("BENCHMARK", "SPY")
SCAN_INTERVAL_MIN = _get("SCAN_INTERVAL_MIN", 10, int)
LOOKBACK_DAYS = _get("LOOKBACK_DAYS", 90, int)

# Momentum sinyal eşikleri
SIGNAL_GAP_THRESHOLD = _get("SIGNAL_GAP_THRESHOLD", 4.0, float)
SIGNAL_VOLUME_THRESHOLD = _get("SIGNAL_VOLUME_THRESHOLD", 2.0, float)

# ═══════════════════════════════════════════════════════════════
# BROAD SCAN (V5.5) — İki Aşamalı Tarama
# ═══════════════════════════════════════════════════════════════
# V5.7: AÇIK default. NASDAQ 100 + Core 15 taranır, pre-filter'dan
# geçenler top N'e indirgenir, sonra detaylı analiz.
# Kapatmak için: BROAD_SCAN_ENABLED=false env var set et.

BROAD_SCAN_ENABLED = _get("BROAD_SCAN_ENABLED", "true").lower() in ("true", "1", "yes")

# Pre-filter (Tier 2 → Claude) eşikleri
PREFILTER_MIN_PRICE = _get("PREFILTER_MIN_PRICE", 10.0, float)        # Penny stock filtresi
PREFILTER_MIN_AVG_VOLUME = _get("PREFILTER_MIN_AVG_VOLUME", 100_000, int)    # IEX feed kalibre (SIP'e geçerken 1_000_000 yap)
PREFILTER_MIN_CHANGE_PCT = _get("PREFILTER_MIN_CHANGE_PCT", 2.0, float)      # |change%| eşiği
PREFILTER_MIN_VOL_RATIO = _get("PREFILTER_MIN_VOL_RATIO", 1.3, float)        # Hacim patlaması eşiği
PREFILTER_TOP_N = _get("PREFILTER_TOP_N", 20, int)                            # Claude'a giden aday sayısı

# ═══════════════════════════════════════════════════════════════
# AKILLI ZAMANLAYICI (V5.6) — Adaptive Scan Frequency
# ═══════════════════════════════════════════════════════════════
# AÇIK default. Tarama sıklığını günün saatine göre ayarlar:
#   Market açık (9:30-16 ET):    her 5 dk   (yoğun mod)
#   Pre-market   (4-9:30 ET):    her 15 dk
#   After-hours  (16-20 ET):     her 30 dk
#   Gece         (20-4 ET):      her 60 dk
#   Hafta sonu   (Cmt-Pzr):      her 180 dk (3 saat)
# Kapatmak için: SMART_SCHEDULE_ENABLED=false → eski 10 dk her zaman

SMART_SCHEDULE_ENABLED = _get("SMART_SCHEDULE_ENABLED", "true").lower() in ("true", "1", "yes")
SMART_INTERVAL_MARKET = _get("SMART_INTERVAL_MARKET", 5, int)        # dk, market açık
SMART_INTERVAL_PREMARKET = _get("SMART_INTERVAL_PREMARKET", 15, int) # dk, pre-market
SMART_INTERVAL_AFTERHOURS = _get("SMART_INTERVAL_AFTERHOURS", 30, int) # dk, after-hours
SMART_INTERVAL_NIGHT = _get("SMART_INTERVAL_NIGHT", 60, int)         # dk, gece
SMART_INTERVAL_WEEKEND = _get("SMART_INTERVAL_WEEKEND", 180, int)    # dk, hafta sonu

# ═══════════════════════════════════════════════════════════════
# SEKTÖR HARİTASI (diversifikasyon kontrolü için)
# ═══════════════════════════════════════════════════════════════

SECTOR_MAP = _file_config.get("SECTOR_MAP", {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "AMZN": "Consumer Cyclical", "TSLA": "Consumer Cyclical",
    "META": "Technology", "AMD": "Technology", "NFLX": "Communication",
    "CRM": "Technology", "AVGO": "Technology", "COIN": "Financial",
    "MARA": "Financial", "SPY": "ETF", "QQQ": "ETF",
})

# ═══════════════════════════════════════════════════════════════
# BRACKET ORDER AYARLARI
# ═══════════════════════════════════════════════════════════════

BRACKET_ENABLED = _get("BRACKET_ENABLED", True, bool)
DEFAULT_RR_RATIO = _get("DEFAULT_RR_RATIO", 2.0, float)          # Risk/Reward oranı

# ═══════════════════════════════════════════════════════════════
# AI APPROVAL
# ═══════════════════════════════════════════════════════════════

AI_APPROVAL_REQUIRED = _get("AI_APPROVAL_REQUIRED", "false").lower() in ("true", "1", "yes")

# ═══════════════════════════════════════════════════════════════
# GEMINI COUNCIL (V4.5)
# ═══════════════════════════════════════════════════════════════

GEMINI_API_KEY = _get("GEMINI_API_KEY", "")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.0-flash")
COUNCIL_ENABLED = _get("COUNCIL_ENABLED", "true").lower() in ("true", "1", "yes")


def get_all() -> dict:
    """Tüm konfigürasyonu döndür (dashboard için)."""
    return {
        "max_risk_pct": MAX_RISK_PCT,
        "max_position_pct": MAX_POSITION_PCT,
        "max_sector_pct": MAX_SECTOR_PCT,
        "atr_multiplier": ATR_MULTIPLIER,
        "order_cooldown_sec": ORDER_COOLDOWN_SEC,
        "flash_crash_threshold": FLASH_CRASH_THRESHOLD,
        "watchlist": WATCHLIST,
        "benchmark": BENCHMARK,
        "scan_interval_min": SCAN_INTERVAL_MIN,
        "ai_model": AI_MODEL,
        "bracket_enabled": BRACKET_ENABLED,
        "default_rr_ratio": DEFAULT_RR_RATIO,
        "ai_approval_required": AI_APPROVAL_REQUIRED,
        "regime_multipliers": REGIME_MULTIPLIERS,
        "regime_max_invested": REGIME_MAX_INVESTED,
        "sector_map": SECTOR_MAP,
        "gemini_model": GEMINI_MODEL,
        "council_enabled": COUNCIL_ENABLED,
    }
