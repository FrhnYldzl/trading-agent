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
    get_asset_group,
    crypto_universe_stats, get_crypto_data,
    CryptoBroker, CryptoRegimeDetector, CryptoScheduler, CryptoRiskManager,
    CryptoBrain, CryptoAuditor, CryptoAutoExecutor,
    get_crypto_news, detect_anomalies,
)
import os

app = FastAPI(title="Trading Agent — Crypto Preview", version="5.10")

# Broker dry_run ayrı env var ile kontrol edilir (default true — paper learning)
_broker_dry_run = (os.getenv("CRYPTO_DRY_RUN", "true").lower()
                   in ("true", "1", "yes"))

# Global instances
_broker = CryptoBroker(dry_run=_broker_dry_run, paper=True)
_regime = CryptoRegimeDetector()
_scheduler = CryptoScheduler()
_risk = CryptoRiskManager()
_brain = CryptoBrain()
_auditor = CryptoAuditor()  # V5.10-δ: Gemini auditor


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
    # CRYPTO_ALPACA_* dedicated key, fallback ALPACA_*
    api_key = os.getenv("CRYPTO_ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("CRYPTO_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    data = get_crypto_data(
        symbols=list(symbols),
        api_key=api_key, secret_key=secret_key,
        lookback_days=lookback_days,
    )
    _cache_set(key, data)
    return data


# ─────────────────────────────────────────────────────────────────
# Auto-executor (V5.10-η iskeleti)
# ─────────────────────────────────────────────────────────────────

_auto_executor = CryptoAutoExecutor(
    broker=_broker,
    brain=_brain,
    regime=_regime,
    risk=_risk,
    scheduler_helper=_scheduler,
    data_fetcher=lambda: _fetch_crypto_md_cached(tuple(CRYPTO_CORE), 60),
    universe=CRYPTO_CORE,
    asset_group_map=CRYPTO_ASSET_GROUP,
    cache_get=_cache_get,
    cache_set=_cache_set,
    auditor=_auditor,  # V5.10-δ: Gemini Council
)


@app.on_event("startup")
def _startup_scheduler():
    """CRYPTO_AUTO_EXECUTE=true ise scheduler başlat."""
    res = _auto_executor.start_scheduler()
    print(f"[CryptoAutoExec] startup: {res}")


@app.on_event("shutdown")
def _shutdown_scheduler():
    _auto_executor.stop_scheduler()


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@app.get("/api/modules")
def modules():
    """
    Cross-module navigation için URL'leri ve renkleri döner.
    Production'da MERIDIAN_*_URL env vars subdomain'e set edilir.
    """
    return {
        "current": "crypto",
        "modules": [
            {
                "id": "equity",
                "label": "Equity",
                "icon": "M",
                "color": "#10b981",
                "url": os.getenv("MERIDIAN_EQUITY_URL", "http://127.0.0.1:8001"),
                "active": True,
            },
            {
                "id": "crypto",
                "label": "Crypto",
                "icon": "₿",
                "color": "#f7931a",
                "url": os.getenv("MERIDIAN_CRYPTO_URL", "http://127.0.0.1:8002"),
                "active": True,
                "current": True,
            },
            {
                "id": "options",
                "label": "Options",
                "icon": "σ",
                "color": "#3b82f6",
                "url": os.getenv("MERIDIAN_OPTIONS_URL", "http://127.0.0.1:8003"),
                "active": False,
                "note": "V5.11'de geliyor",
            },
        ],
    }


@app.get("/api/crypto/health")
def health():
    journal_path = _auto_executor.journal.db_path
    journal_persistent = (
        "/app/data" in journal_path
        or os.getenv("JOURNAL_DB_PATH") is not None
    )
    return {
        "status": "ok",
        "module": "crypto",
        "version": "5.10",  # V5.10 final — α/β/γ/δ/ε/ζ/η hepsi tamam
        "asset_class": "crypto",
        "dry_run": _broker.dry_run,
        "paper": _broker.paper,
        "account_label": _broker.account_label,
        "is_dedicated_account": _broker.is_dedicated_account,
        "brain_enabled": _brain.enabled,
        "brain_api_key_source": _brain.api_key_source,
        "auditor_enabled": _auditor.enabled,
        "auditor_api_key_source": _auditor.api_key_source,
        "journal_db_path": journal_path,
        "journal_persistent": journal_persistent,
        "color": "#f7931a",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/crypto/audit")
def audit_status():
    """Son Gemini audit sonuçları."""
    return _auditor.get_last_audit()


@app.get("/api/crypto/news")
def news_endpoint(force: bool = False):
    """V5.10-β: Crypto news + sentiment (10dk cache)."""
    return get_crypto_news(force_refresh=force)


@app.get("/api/crypto/anomalies")
def anomalies_endpoint():
    """V5.10-γ: Anomaly detection — flash dump, vol spike, market stress."""
    md = _fetch_crypto_md_cached(tuple(CRYPTO_CORE), 60)
    return detect_anomalies(md)


@app.get("/api/crypto/env-debug")
def env_debug():
    """
    Diagnostic endpoint — sadece env var İSİMLERİ ve değerlerin BAŞINI
    döner (güvenli). Hangi env var'ların container'a inject edildiğini
    görmek için.
    """
    out = []
    for k, v in os.environ.items():
        if not isinstance(v, str):
            continue
        # Sensitive prefix'lerini maskele
        if v.startswith("sk-ant-"):
            preview = "sk-ant-...(found)"
        elif v.startswith("PK"):
            preview = v[:4] + "..."
        elif len(v) > 40:
            preview = "(long value, hidden)"
        elif "key" in k.lower() or "secret" in k.lower() or "token" in k.lower():
            preview = "(sensitive, hidden)"
        else:
            preview = v[:50]
        out.append({"name": k, "preview": preview})
    out.sort(key=lambda x: x["name"])
    return {
        "env_var_count": len(out),
        "looks_like_anthropic_key_present": any(
            v.startswith("sk-ant-") for v in os.environ.values()
            if isinstance(v, str)
        ),
        "vars": out,
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
                "asset_group": get_asset_group(p.symbol),
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


@app.get("/api/crypto/overview-charts")
def overview_charts(timeframe: str = "1Day", days: int = 30):
    """
    Overview sayfası için tek-istek: BTC + her açık pozisyon için bar verisi.
    BTC her zaman dahil. Pozisyonların entry fiyatı, qty, P&L overlay için.

    30sn cache (bars endpoint'i ile aynı TTL).
    """
    cache_key = f"overview-charts:{timeframe}:{days}"
    hit = _cache_get(cache_key, ttl=30)
    if hit is not None:
        return hit

    out = {"btc": None, "positions": []}

    # 1. BTC her zaman göster
    btc = bars("BTC/USD", timeframe=timeframe, days=days)
    out["btc"] = {
        "symbol": "BTC/USD",
        "bars": btc.get("bars", []),
        "asset_group": CRYPTO_ASSET_GROUP.get("BTC/USD", "L1"),
    }

    # 2. Açık crypto pozisyonları topla
    try:
        all_positions = _broker.client.get_all_positions()
        crypto_positions = [
            p for p in all_positions
            if p.asset_class and "crypto" in str(p.asset_class).lower()
        ]
    except Exception as e:
        out["error"] = f"positions fetch: {e}"
        crypto_positions = []

    for p in crypto_positions:
        sym = p.symbol
        # Alpaca bazen slash'sız döner — chart endpoint'i için slash'lı versiyona çevir
        if "/" not in sym and sym.endswith("USD"):
            sym_slash = sym[:-3] + "/USD"
        else:
            sym_slash = sym
        b = bars(sym_slash, timeframe=timeframe, days=days)
        out["positions"].append({
            "symbol": sym_slash,
            "bars": b.get("bars", []),
            "asset_group": CRYPTO_ASSET_GROUP.get(sym_slash, "Unknown"),
            "position": {
                "qty": float(p.qty),
                "side": str(p.side),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            },
        })

    out["timeframe"] = timeframe
    out["days"] = days
    out["count"] = 1 + len(crypto_positions)  # BTC + position chartları
    _cache_set(cache_key, out)
    return out


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


@app.get("/api/crypto/brain")
def brain_decisions(fresh: bool = False):
    """
    Claude AI Crypto Brain — multi-step reasoning.
    60sn cache. ?fresh=true ile bypass.
    """
    cache_key = "brain:core10"
    if not fresh:
        hit = _cache_get(cache_key, ttl=60)
        if hit is not None:
            return hit

    if not _brain.enabled:
        return {
            "error": (
                "Claude API key bulunamadı. "
                f"Source: {_brain.api_key_source}. "
                "Railway Variables tab'ında değeri 'sk-ant-' ile başlayan "
                "bir env var ekle (örn. MERIDIAN_CRYPTO_TERMINAL ya da "
                "ANTHROPIC_API_KEY). İsim boşluksuz, sadece A-Z/0-9/_ olmalı."
            ),
            "api_key_source": _brain.api_key_source,
            "decisions": [],
            "regime": "unknown",
        }

    # 1. Market data (cached)
    md = _fetch_crypto_md_cached(tuple(CRYPTO_CORE), 60)

    # 2. Regime (cached)
    rkey = "regime:core10"
    regime = _cache_get(rkey)
    if regime is None:
        regime = _regime.detect(md)
        _cache_set(rkey, regime)

    # 3. Portfolio
    try:
        acct = _broker.client.get_account()
        positions = _broker.client.get_all_positions()
        crypto_positions = [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "unrealized_pl": float(p.unrealized_pl),
                "asset_group": get_asset_group(p.symbol),
            }
            for p in positions
            if p.asset_class and "crypto" in str(p.asset_class).lower()
        ]
        portfolio = {
            "cash": float(acct.cash),
            "equity": float(acct.equity),
            "positions": crypto_positions,
        }
    except Exception as e:
        portfolio = {"cash": 0, "equity": 0, "positions": [], "error": str(e)}

    # 4. Brain
    result = _brain.run_brain(
        market_data=md,
        portfolio=portfolio,
        recent_trades=[],         # V5.10-ε'da journal'dan gelecek
        regime=regime,
        sentiment=None,            # V5.10-β'da news'tan gelecek
        learning_context=None,     # V5.10-ε'da journal'dan gelecek
    )

    _cache_set(cache_key, result)
    return result


@app.get("/api/crypto/journal")
def journal_recent(limit: int = 100, event_type: str = None, symbol: str = None):
    """Son N journal kaydı, filtre opsiyonel (event_type/symbol)."""
    return {
        "entries": _auto_executor.journal.get_recent(
            limit=limit, event_type=event_type, symbol=symbol,
        ),
        "filters": {"limit": limit, "event_type": event_type, "symbol": symbol},
    }


@app.get("/api/crypto/journal/performance")
def journal_performance(days: int = 30):
    """Aggregate stats — son N gün."""
    return _auto_executor.journal.get_performance(days=days)


@app.get("/api/crypto/journal/run/{pipeline_run_id}")
def journal_run_timeline(pipeline_run_id: str):
    """Tek bir run'ın tüm event'leri (timeline view için)."""
    return {
        "pipeline_run_id": pipeline_run_id,
        "events": _auto_executor.journal.get_by_pipeline_run(pipeline_run_id),
    }


@app.get("/api/crypto/journal/open-trades")
def journal_open_trades():
    """Açık (henüz kapatılmamış) trade'ler."""
    return {"open_trades": _auto_executor.journal.get_open_trades()}


@app.get("/api/crypto/scheduler-status")
def scheduler_status():
    """Auto-executor + safety gates state."""
    return _auto_executor.get_status()


@app.post("/api/crypto/run-now")
def run_now():
    """
    Manuel pipeline trigger — auto_execute kapalıyken bile çalışır.
    Broker dry_run ON ise gerçek emir gitmez.
    """
    return _auto_executor.run_once(force=True)


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
    """Bloomberg-grade BTC-themed crypto trading terminal.

    Cache busting: HTML her zaman fresh çekilir (Cache-Control: no-store).
    Bu sayede deploy sonrası browser eski JS'le takılı kalmaz.
    """
    return FileResponse(
        _static_dir / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Static asset mounting (CSS/JS dosyaları lazım olursa)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
