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

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

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
# Root HTML — minimal, hızlı bakış
# ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    html = """
<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Crypto Preview — Trading Agent V5.9-α</title>
<style>
  body { font-family: -apple-system, monospace; background: #0a0a0a; color: #e0e0e0;
         padding: 24px; max-width: 980px; margin: 0 auto; }
  h1 { color: #f7931a; border-bottom: 1px solid #333; padding-bottom: 8px; }
  h2 { color: #4ade80; margin-top: 28px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 3px;
           font-size: 12px; margin-left: 8px; }
  .dry { background: #f59e0b; color: #000; }
  .paper { background: #3b82f6; color: #fff; }
  ul { line-height: 1.8; }
  a { color: #60a5fa; text-decoration: none; }
  a:hover { text-decoration: underline; }
  code { background: #1a1a1a; padding: 2px 6px; border-radius: 3px; color: #f7931a; }
  .warn { background: #7c2d12; padding: 12px; border-radius: 6px; margin: 16px 0; }
</style>
</head><body>
<h1>🟠 Crypto Preview — Trading Agent V5.9-α</h1>
<span class="badge dry">DRY-RUN</span>
<span class="badge paper">PAPER</span>

<div class="warn">
⚠️ Bu standalone preview ana sistemden ayrıdır. Tüm crypto broker
metotları <code>dry_run=True</code> ile init edilmiştir — gerçek
emir gönderilmez. Ana equity preview (8001) ve Railway deploy
etkilenmez.
</div>

<h2>Live API Endpoints</h2>
<ul>
  <li><a href="/api/crypto/health">/api/crypto/health</a> — server durumu</li>
  <li><a href="/api/crypto/universe">/api/crypto/universe</a> — Core 10 + Extended 33 + asset groups</li>
  <li><a href="/api/crypto/account">/api/crypto/account</a> — Alpaca hesap (cash, equity, buying power)</li>
  <li><a href="/api/crypto/market-data">/api/crypto/market-data</a> — Core 10 canlı OHLCV + EMA/RSI/ATR</li>
  <li><a href="/api/crypto/regime">/api/crypto/regime</a> — BTC-benchmarked rejim algılaması</li>
  <li><a href="/api/crypto/positions">/api/crypto/positions</a> — açık crypto pozisyonları</li>
  <li><a href="/api/crypto/orders">/api/crypto/orders</a> — bekleyen crypto emirleri</li>
  <li><a href="/api/crypto/scheduler">/api/crypto/scheduler</a> — 24/7 mod + interval</li>
  <li><a href="/api/crypto/risk-config">/api/crypto/risk-config</a> — kalibre risk parametreleri</li>
</ul>

<h2>Mimari</h2>
<ul>
  <li><code>crypto/universe.py</code> — Core 10 + Extended 33 (stablecoin'ler hariç)</li>
  <li><code>crypto/data.py</code> — Alpaca <code>CryptoHistoricalDataClient</code> wrapper</li>
  <li><code>crypto/broker_impl.py</code> — <code>BaseBroker</code> impl, <strong>dry_run zorunlu</strong></li>
  <li><code>crypto/risk_impl.py</code> — <code>BaseRiskManager</code> impl, %1 max risk + asset group concentration</li>
  <li><code>crypto/regime_impl.py</code> — <code>BaseRegimeDetector</code> impl, BTC benchmark</li>
  <li><code>crypto/scheduler_impl.py</code> — <code>BaseScheduler</code> impl, 24/7 + weekend slowdown</li>
</ul>

<p style="color: #888; margin-top: 32px; font-size: 12px;">
Brain (Claude AI prompt) ve auto-trading scheduler V5.9-β/γ'da eklenecek.
Şu anda sistem <strong>read-only</strong> — sadece veri çekiyor, karar vermiyor.
</p>
</body></html>
"""
    return HTMLResponse(content=html)
