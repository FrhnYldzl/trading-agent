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
