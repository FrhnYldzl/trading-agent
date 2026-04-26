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

app = FastAPI(title="Trading Agent — Crypto Preview", version="5.9-α")

# Global instances — singleton tarzı, dry_run ZORUNLU
_broker = CryptoBroker(dry_run=True, paper=True)
_regime = CryptoRegimeDetector()
_scheduler = CryptoScheduler()
_risk = CryptoRiskManager()


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
    md = get_crypto_data(
        symbols=CRYPTO_CORE,
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        lookback_days=60,
    )
    return md


@app.get("/api/crypto/regime")
def regime():
    md = get_crypto_data(
        symbols=CRYPTO_CORE,
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        lookback_days=60,
    )
    return _regime.detect(md)


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
