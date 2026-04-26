"""
crypto_preview_app.py — Standalone FastAPI app for crypto module preview.

Mevcut main.py'a HİÇ DOKUNMAZ. Ayrı bir port'ta (8002) çalışır.
Equity preview (8001) ve Railway main deploy hiçbir şekilde etkilenmez.

Çalıştır:
    uvicorn crypto_preview_app:app --host 127.0.0.1 --port 8002

Endpoint'ler:
    GET  /                       → HTML preview sayfası (basit)
    GET  /api/crypto/health      → Server status
    GET  /api/crypto/universe    → Core 10 + Extended + asset group haritası
    GET  /api/crypto/account     → Alpaca hesap durumu (paper)
    GET  /api/crypto/market-data → Core 10 OHLCV + indikatörler (canlı)
    GET  /api/crypto/regime      → BTC-benchmark rejim
    GET  /api/crypto/positions   → Açık crypto pozisyonlar
    GET  /api/crypto/scheduler   → 24/7 mod + sıradaki tarama interval'i
    GET  /api/crypto/orders      → Bekleyen crypto emirleri
"""

from datetime import datetime, timezone
from pathlib import Path
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv("../.env")  # repo kökündeki .env

from crypto import (
    CRYPTO_CORE, CRYPTO_EXTENDED, STABLECOINS, CRYPTO_ASSET_GROUP,
    crypto_universe_stats, get_crypto_data,
    CryptoBroker, CryptoRegimeDetector, CryptoScheduler, CryptoRiskManager,
)
import os

app = FastAPI(title="Trading Agent — Crypto Preview", version="5.9-δ")

# Global instances — singleton tarzı, dry_run ZORUNLU
_broker = CryptoBroker(dry_run=True, paper=True)
_regime = CryptoRegimeDetector()
_scheduler = CryptoScheduler()
_risk = CryptoRiskManager()


# ─────────────────────────────────────────────────────────────────
# TTL Cache — basit dict, dashboard hız için
# ─────────────────────────────────────────────────────────────────
# Alpaca crypto API her çağrıda 1-3sn alıyor; aynı veriyi 30sn TTL ile
# tekrar kullanmak dashboard'u keskin bir şekilde hızlandırır.
# Cache bypass: ?fresh=true parametresi ile.

_cache: dict = {}
DEFAULT_TTL = 30  # saniye

def _cache_get(key: str, ttl: int = DEFAULT_TTL):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None

def _cache_set(key: str, data):
    _cache[key] = {"ts": time.time(), "data": data}

def _fetch_crypto_md_cached(symbols: tuple, lookback_days: int = 60):
    """Cached crypto market data fetch."""
    key = f"md:{','.join(symbols)}:{lookback_days}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    data = get_crypto_data(
        symbols=list(symbols),
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        lookback_days=lookback_days,
    )
    _cache_set(key, data)
    return data


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@app.get("/api/crypto/health")
def health():
    return {
        "status": "ok",
        "module": "crypto",
        "version": "5.9-α",
        "asset_class": "crypto",
        "dry_run": _broker.dry_run,
        "paper": _broker.paper,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/crypto/universe")
def universe():
    stats = crypto_universe_stats()
    return {
        "core": CRYPTO_CORE,
        "extended": CRYPTO_EXTENDED,
        "stablecoins_excluded": STABLECOINS,
        "stats": stats,
        "asset_groups": CRYPTO_ASSET_GROUP,
    }


@app.get("/api/crypto/account")
def account():
    return _broker.get_account_status()


@app.get("/api/crypto/market-data")
def market_data():
    """Core 10 OHLCV — 30sn cache."""
    return _fetch_crypto_md_cached(tuple(CRYPTO_CORE), 60)


@app.get("/api/crypto/regime")
def regime():
    """Core 10 üzerinden BTC-benchmark regime — 30sn cache (md cache'lenmiş)."""
    md = _fetch_crypto_md_cached(tuple(CRYPTO_CORE), 60)
    # Regime hesabı kendisi de cache'lensin (key md cache'i ile aynı dönemde)
    rkey = "regime:core10"
    hit = _cache_get(rkey)
    if hit is not None:
        return hit
    result = _regime.detect(md)
    _cache_set(rkey, result)
    return result


@app.get("/api/crypto/positions")
def positions():
    """Açık crypto pozisyonları."""
    try:
        all_positions = _broker.client.get_all_positions()
        crypto_positions = []
        for p in all_positions:
            ac = str(p.asset_class).lower() if p.asset_class else ""
            if "crypto" not in ac:
                continue
            crypto_positions.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "asset_group": CRYPTO_ASSET_GROUP.get(p.symbol, "Unknown"),
            })
        return {"positions": crypto_positions, "count": len(crypto_positions)}
    except Exception as e:
        return {"error": str(e), "positions": [], "count": 0}


@app.get("/api/crypto/scheduler")
def scheduler():
    mode, interval = _scheduler.detect_scan_mode()
    return {
        "mode": mode,
        "interval_minutes": interval,
        "is_active_session": _scheduler.is_active_session(),
        "asset_class": "crypto",
        "note": "Crypto 24/7 — is_active_session her zaman True.",
    }


@app.get("/api/crypto/orders")
def pending_orders():
    return {"orders": _broker.get_pending_orders()}


@app.get("/api/crypto/extended-data")
def extended_data(min_change: float = 0.0, min_vol_ratio: float = 0.0):
    """
    Extended 33 (tüm tradable USD pair'ler, stablecoin'siz) için OHLCV +
    indikatörler. Opsiyonel filtreler: min_change (mutlak değer %), min_vol_ratio.
    Cache 30sn — dashboard tablosu hızlı yüklenir.
    """
    md = _fetch_crypto_md_cached(tuple(CRYPTO_EXTENDED), 60)
    # Filter uygula (opsiyonel)
    if min_change > 0 or min_vol_ratio > 0:
        filtered = {}
        for sym, d in md.items():
            if sym.startswith("_"):
                filtered[sym] = d
                continue
            if "error" in d:
                continue
            change = abs(d.get("change_pct", 0))
            vol_r = d.get("volume_ratio", 0) or 0
            if change >= min_change and vol_r >= min_vol_ratio:
                filtered[sym] = d
        return filtered
    return md


@app.get("/api/crypto/bars/{symbol_path:path}")
def bars(symbol_path: str, timeframe: str = "1Day", days: int = 30):
    """
    Tek sembol için OHLCV bar'ları — chart için. 60sn cache.

    symbol_path: "BTC/USD" (URL'de slash kullanılabilir)
    timeframe: 1Min, 5Min, 15Min, 1Hour, 4Hour, 1Day, 1Week
    days: lookback gün sayısı
    """
    cache_key = f"bars:{symbol_path}:{timeframe}:{days}"
    hit = _cache_get(cache_key, ttl=60)
    if hit is not None:
        return hit

    from datetime import timedelta
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    tf_map = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame.Day,
        "1Week": TimeFrame.Week,
    }
    tf = tf_map.get(timeframe, TimeFrame.Day)

    try:
        client = CryptoHistoricalDataClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        req = CryptoBarsRequest(
            symbol_or_symbols=[symbol_path],
            timeframe=tf,
            start=start, end=end,
        )
        bars = client.get_crypto_bars(req)
        ticker_bars = bars[symbol_path]
        out = [
            {
                "t": b.timestamp.isoformat(),
                "o": float(b.open),
                "h": float(b.high),
                "l": float(b.low),
                "c": float(b.close),
                "v": float(b.volume),
            }
            for b in ticker_bars
        ]
        result = {
            "symbol": symbol_path,
            "timeframe": timeframe,
            "days": days,
            "bars": out,
            "count": len(out),
        }
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        return {"symbol": symbol_path, "error": str(e), "bars": [], "count": 0}


@app.get("/api/crypto/symbol-summary/{symbol_path:path}")
def symbol_summary(symbol_path: str):
    """
    Tek bir sembol için chart sayfasının ihtiyacı olan her şey:
      - latest market data (price, change, RSI, ATR, trend)
      - varsa açık pozisyon (avg_entry, qty, market_value, P&L)
      - asset_group bilgisi
    Tek istek = tek panel. Frontend chart + position'ı yan yana koyar.
    """
    sym = symbol_path.upper()
    md = _fetch_crypto_md_cached(tuple(CRYPTO_EXTENDED), 60)
    coin = md.get(sym, {}) if not md.get(sym, {}).get("error") else {}

    position = _broker.get_position(sym)
    asset_group = CRYPTO_ASSET_GROUP.get(sym, "Unknown")

    return {
        "symbol": sym,
        "asset_group": asset_group,
        "market": {
            "price": coin.get("price"),
            "change_pct": coin.get("change_pct"),
            "rsi14": coin.get("rsi14"),
            "atr_pct": coin.get("atr_pct"),
            "trend": coin.get("trend"),
            "ema9": coin.get("ema9"),
            "ema21": coin.get("ema21"),
            "ema50": coin.get("ema50"),
            "momentum_score": coin.get("momentum_score"),
            "volume_ratio": coin.get("volume_ratio"),
        },
        "position": position,  # None ya da {symbol, qty, avg_entry, ...}
        "has_position": position is not None,
    }


@app.get("/api/crypto/risk-config")
def risk_config():
    return {
        "max_risk_pct": _risk.DEFAULT_MAX_RISK_PCT,
        "max_group_pct": _risk.DEFAULT_GROUP_MAX_PCT,
        "asset_groups": list(set(CRYPTO_ASSET_GROUP.values())),
        "default_atr_multiplier": 2.0,
        "default_stop_pct": 0.04,
        "note": "Crypto kalibrasyonu: equity'nin %50 risk'i, 2x ATR çarpanı.",
    }


# ─────────────────────────────────────────────────────────────────
# Static dashboard — Meridian Capital Crypto Terminal
# ─────────────────────────────────────────────────────────────────

_static_dir = Path(__file__).parent / "static" / "crypto"

@app.get("/", response_class=HTMLResponse)
def root():
    """Bloomberg-grade BTC-themed crypto trading terminal."""
    return FileResponse(_static_dir / "index.html")


# Static asset mounting (CSS/JS dosyaları lazım olursa)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
