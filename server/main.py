"""
main.py — AI Trading Agent V2 Sunucusu

Artik sadece bir webhook sunucu degil — otonom bir trading agent.

Katmanlar:
  1. Data Layer   : Alpaca Data API (market_scanner.py)
  2. Brain Layer  : Claude AI (claude_brain.py) — rejim + strateji + multi-step reasoning
  3. Risk Layer   : Dinamik pozisyon boyutlandirma (risk_manager.py)
  4. Execution    : Alpaca Trading API (broker/equity.py)
  5. Storage      : SQLite (database.py) + post-trade review

Baslatmak icin:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Dashboard:
    http://localhost:8000
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from broker.equity import EquityBroker
from database import get_recent_trades, init_db, log_trade, clear_old_trades
from trade_journal import (
    init_journal_db, log_journal_entry, get_journal_entries,
    calculate_performance, generate_lesson, get_learning_context,
)
from risk_manager import RiskManager
from ai_advisor import analyze_trade, review_strategy, is_enabled
import scheduler as sched
from market_scanner import get_market_data, WATCHLIST
import config as cfg

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

# ──────────────────────────────────────────────────────────────────
# WebSocket baglanti yöneticisi (canli bildirimler icin)
# ──────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

# ──────────────────────────────────────────────────────────────────
# Uygulama baslatma
# ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # V2: Scheduler — her 10 dk tarama, piyasa acik/kapali farketmez
    sched.start(broker=broker, auto_execute=False, interval_minutes=10)
    print("AI Trading Agent V2 baslatildi >> http://localhost:8000")
    yield
    sched.stop()

app = FastAPI(
    title="AI Trading Agent V2",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ──────────────────────────────────────────────────────────────────
# Sabitler
# ──────────────────────────────────────────────────────────────────

WEBHOOK_SECRET = cfg.WEBHOOK_SECRET
MAX_RISK_PCT = cfg.MAX_RISK_PCT
AI_APPROVAL_REQUIRED = cfg.AI_APPROVAL_REQUIRED

broker = EquityBroker()
risk = RiskManager(max_risk_pct=MAX_RISK_PCT)

# ──────────────────────────────────────────────────────────────────
# Veri Modelleri
# ──────────────────────────────────────────────────────────────────

class Signal(BaseModel):
    ticker: str = Field(..., examples=["AAPL"])
    action: str = Field(..., examples=["long"])
    price: float = Field(..., gt=0)
    qty: float | None = Field(None, gt=0)
    secret: str | None = None

# ──────────────────────────────────────────────────────────────────
# Dashboard (kök sayfa)
# ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

# ──────────────────────────────────────────────────────────────────
# WebSocket — canli islem bildirimleri
# ──────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ──────────────────────────────────────────────────────────────────
# API Endpoint'leri
# ──────────────────────────────────────────────────────────────────

@app.post("/webhook")
async def handle_webhook(signal: Signal):
    if WEBHOOK_SECRET and signal.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Gecersiz webhook secret.")

    loop = asyncio.get_event_loop()

    if signal.qty:
        qty = signal.qty
    else:
        balance = await loop.run_in_executor(None, broker.get_balance)
        qty = risk.calculate_position_size(
            balance=balance,
            entry_price=signal.price,
            stop_loss_pct=0.02,
        )

    # Claude AI Analizi
    recent = get_recent_trades(limit=5)
    balance_for_ai = await loop.run_in_executor(None, broker.get_balance)
    ai_analysis = await loop.run_in_executor(
        None,
        partial(analyze_trade,
            ticker=signal.ticker,
            action=signal.action,
            price=signal.price,
            qty=qty,
            balance=balance_for_ai,
            recent_trades=recent,
        )
    )

    # AI onay zorunluysa ve reddedildiyse dur
    if AI_APPROVAL_REQUIRED and not ai_analysis.get("approved", True):
        raise HTTPException(
            status_code=400,
            detail=f"AI Advisor reddetti: {ai_analysis.get('reasoning')}"
        )

    # Islemi gerceklestir (V2.1: guvenlik kontrolleri broker icinde)
    try:
        result = await loop.run_in_executor(
            None,
            partial(broker.execute,
                action=signal.action,
                ticker=signal.ticker,
                qty=qty,
                price=signal.price,
            )
        )
    except Exception as e:
        err = {"status": "error", "message": str(e)}
        signal.qty = qty
        log_trade(signal, err)
        raise HTTPException(status_code=400, detail=str(e))

    # V2.1: Broker rejected kontrolu (loop/market/price kontrolleri)
    if result.get("status") == "rejected":
        signal.qty = qty
        log_trade(signal, result)
        raise HTTPException(
            status_code=400,
            detail=f"Emir reddedildi: {result.get('reason', 'Bilinmeyen neden')}"
        )

    signal.qty = qty
    log_trade(signal, result)

    # Dashboard'a canli bildirim + AI yorumu gönder
    await manager.broadcast({
        "type": "new_trade",
        "ticker": signal.ticker,
        "action": signal.action,
        "qty": qty,
        "price": signal.price,
        "status": result.get("status"),
        "ai": ai_analysis,
    })

    return {
        "status": "ok",
        "ticker": signal.ticker,
        "action": signal.action,
        "qty": qty,
        "result": result,
        "ai_analysis": ai_analysis,
    }


@app.get("/api/trades")
async def list_trades(limit: int = 50):
    return get_recent_trades(limit=limit)


@app.get("/api/account")
async def get_account():
    try:
        account = broker.client.get_account()
        positions = broker.client.get_all_positions()
        has_pending = float(account.buying_power) < float(account.cash) * 2
        return {
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "has_pending": has_pending,
            "positions": [
                {
                    "ticker": p.symbol,
                    "qty": float(p.qty),
                    "avg_entry": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": round(float(p.unrealized_plpc) * 100, 2),
                }
                for p in positions
            ],
        }
    except Exception as e:
        return {"error": str(e), "cash": 0, "portfolio_value": 0, "equity": 0, "buying_power": 0, "has_pending": False, "positions": []}


@app.get("/api/recommendations")
async def get_recommendations():
    """Son Claude tarama kararlarini döndürür — V2: rejim + strateji + güven skoru."""
    return sched.get_last_scan()


@app.post("/api/scan-now")
async def trigger_scan():
    """Manuel tarama baslat (dashboard'dan tetiklenebilir)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: sched.run_scan(broker=broker, auto_execute=False)
    )
    return sched.get_last_scan()


@app.get("/api/watchlist")
async def get_watchlist():
    return {"watchlist": WATCHLIST}


@app.get("/api/strategy-review")
async def strategy_review():
    """Tüm islem gecmisini analiz edip strateji önerileri üretir."""
    trades = get_recent_trades(limit=50)
    return review_strategy(trades)


@app.get("/api/post-trade-review")
async def post_trade_review():
    """Son post-trade review sonucunu döndürür."""
    return sched.get_last_review()


@app.post("/api/run-review")
async def trigger_review():
    """Manuel post-trade review tetikle."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: sched.run_review(broker=broker)
    )
    return sched.get_last_review()


@app.get("/api/risk-check")
async def risk_check():
    """Portföy risk analizi — rejime göre uyumluluk kontrolü."""
    try:
        account = broker.client.get_account()
        positions = broker.client.get_all_positions()
        equity = float(account.equity)
        pos_list = [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "current_price": float(p.current_price),
            }
            for p in positions
        ]
        last_scan = sched.get_last_scan()
        regime = last_scan.get("regime", "neutral")
        return risk.portfolio_risk_check(equity, pos_list, regime)
    except Exception as e:
        return {"error": str(e), "warnings": [str(e)]}


@app.get("/api/ai-status")
async def ai_status():
    last_scan = sched.get_last_scan()
    return {
        "enabled": is_enabled(),
        "approval_required": AI_APPROVAL_REQUIRED,
        "model": "claude-sonnet-4-6",
        "regime": last_scan.get("regime", "unknown"),
        "active_strategy": last_scan.get("active_strategy", "none"),
        "session_mode": last_scan.get("session_mode", "unknown"),
        "last_scan": last_scan.get("timestamp"),
    }


@app.post("/api/clear-trades")
async def clear_trades():
    """Eski test islem verilerini temizle."""
    return clear_old_trades()


@app.get("/api/journal")
async def get_journal(limit: int = 20):
    """Islem gunlugu — gecmis dersler."""
    return get_journal_entries(limit=limit)


@app.get("/api/performance")
async def get_performance():
    """Performans metrikleri — win rate, profit factor, drawdown."""
    return calculate_performance()


@app.post("/api/cancel-orders")
async def cancel_orders():
    """Tum bekleyen emirleri iptal et (pre-market cleanup)."""
    return broker.cancel_all_orders()


@app.get("/api/pending-orders")
async def pending_orders():
    """Bekleyen emirleri listele."""
    return broker.get_pending_orders()


@app.get("/api/account-status")
async def account_status():
    """Detayli hesap durumu — PDT, trading blocked, etc."""
    return broker.get_account_status()


@app.post("/api/approve-trade")
async def approve_trade(data: dict):
    """
    Dashboard'dan islem onaylama.
    Claude'un onerdigini kullanici onaylar, agent uygular.
    Safety rope: otonom mod oncesi son kontrol noktasi.
    """
    ticker = data.get("ticker", "")
    action = data.get("action", "")
    confidence = data.get("confidence", 0)
    entry_zone = data.get("entry_zone", "")

    if not ticker or not action:
        raise HTTPException(status_code=400, detail="ticker ve action gerekli")

    if action in ("hold", "watch"):
        return {"status": "skipped", "reason": "hold/watch icin islem yapilmaz"}

    loop = asyncio.get_event_loop()

    # Gercek fiyati al
    try:
        market_data = await loop.run_in_executor(None, get_market_data)
        ticker_data = market_data.get(ticker, {})
        current_price = ticker_data.get("price", 0)
        atr = ticker_data.get("atr14", current_price * 0.02)
    except Exception:
        raise HTTPException(status_code=400, detail="Fiyat verisi alinamadi")

    if current_price <= 0:
        raise HTTPException(status_code=400, detail=f"{ticker} icin fiyat bulunamadi")

    # Dinamik pozisyon boyutlandirma
    last_scan = sched.get_last_scan()
    regime = last_scan.get("regime", "neutral")

    stop_price = risk.atr_stop_loss(current_price, atr, "long" if action == "long" else "short")
    balance = await loop.run_in_executor(None, broker.get_balance)
    equity = balance  # Basitlestirilmis

    sizing = risk.dynamic_position_size(
        equity=equity,
        entry_price=current_price,
        stop_loss_price=stop_price,
        confidence=confidence,
        regime=regime,
    )

    qty = sizing.get("qty", 0)
    if qty <= 0:
        return {"status": "rejected", "reason": "Pozisyon boyutu 0 — guven skoru cok dusuk"}

    # Emri gonder
    try:
        result = await loop.run_in_executor(
            None,
            partial(broker.execute,
                action=action,
                ticker=ticker,
                qty=qty,
                price=current_price,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result.get("status") == "rejected":
        return result

    # Trade journal'a kaydet
    from trade_journal import log_journal_entry
    log_journal_entry(
        ticker=ticker,
        action=action,
        entry_price=current_price,
        qty=qty,
        ai_prediction=f"confidence={confidence}",
        ai_confidence=confidence,
        strategy_used=last_scan.get("active_strategy", ""),
        regime=regime,
    )

    # Dashboard'a bildir
    await manager.broadcast({
        "type": "new_trade",
        "ticker": ticker,
        "action": action,
        "qty": qty,
        "price": current_price,
        "status": result.get("status"),
        "source": "manual_approval",
    })

    return {
        "status": "ok",
        "ticker": ticker,
        "action": action,
        "qty": qty,
        "price": current_price,
        "sizing": sizing,
        "result": result,
    }


@app.get("/api/config")
async def get_config():
    """V3: Tüm konfigürasyonu döndür."""
    return cfg.get_all()


@app.get("/api/risk-metrics")
async def risk_metrics():
    """V3: Sharpe Ratio, Sortino, VaR hesapla."""
    journal = get_journal_entries(limit=100)
    returns = [
        e.get("pnl_pct", 0) for e in journal
        if isinstance(e, dict) and e.get("pnl_pct") is not None and e.get("pnl_pct") != 0
    ]
    return risk.calculate_risk_metrics(returns)


@app.get("/api/sector-exposure")
async def sector_exposure():
    """V3: Sektör bazlı portföy dağılımı."""
    try:
        account = broker.client.get_account()
        positions = broker.client.get_all_positions()
        equity = float(account.equity)
        pos_list = [
            {"ticker": p.symbol, "qty": float(p.qty), "current_price": float(p.current_price)}
            for p in positions
        ]
        return risk.check_sector_exposure(equity, pos_list)
    except Exception as e:
        return {"error": str(e), "sectors": {}, "warnings": []}


@app.get("/api/flash-crash-check")
async def flash_crash_check():
    """V3: Flash crash kontrol — anlık büyük düşüş tespiti."""
    try:
        positions = broker.client.get_all_positions()
        pos_list = [
            {"ticker": p.symbol, "qty": float(p.qty), "current_price": float(p.current_price)}
            for p in positions
        ]
        loop = asyncio.get_event_loop()
        market_data = await loop.run_in_executor(None, get_market_data)
        return risk.check_flash_crash(pos_list, market_data)
    except Exception as e:
        return {"flash_crash_detected": False, "alerts": [], "error": str(e)}


@app.post("/api/emergency-liquidate")
async def emergency_liquidate():
    """V3: Acil durum — tüm pozisyonları kapat."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, broker.emergency_liquidate)
    await manager.broadcast({"type": "emergency_liquidate", "result": result})
    return result


@app.get("/api/health")
async def health():
    last_scan = sched.get_last_scan()
    return {
        "status": "ok",
        "version": "3.0",
        "ai_enabled": is_enabled(),
        "regime": last_scan.get("regime", "unknown"),
        "session_mode": last_scan.get("session_mode", "unknown"),
        "last_scan": last_scan.get("timestamp"),
    }
