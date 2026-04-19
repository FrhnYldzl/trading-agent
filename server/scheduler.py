"""
scheduler.py — Otonom Tarama Zamanlayicisi (V2)

V1: 30 dk interval, piyasa kapali = durdur
V2: Sürekli döngü, piyasa kapali = analiz + hazirlik modu

Modlar:
  - Pre-market (08:00-13:30 UTC): Gap taramasi, günün planini olustur
  - Market open (13:30-20:00 UTC): Aktif tarama, 5 dk interval
  - After-hours (20:00-08:00 UTC): Post-trade review, yarin hazirlik

Her modda Claude beyni calisir, sadece islem tetikleme modu degisir.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from market_scanner import get_market_data, is_market_open, is_premarket
from claude_brain import run_brain, review_past_trades, pdt_trades_left
from database import get_recent_trades
from trade_journal import init_journal_db, get_learning_context
from notifier import send_trade_notification, send_daily_summary, is_enabled as notify_enabled

DB_PATH = Path(__file__).parent / "trades.db"

# Son tarama sonucu (dashboard icin)
_last_scan: dict = {
    "status": "Henuz tarama yapilmadi",
    "timestamp": None,
    "decisions": [],
    "regime": "unknown",
    "regime_reasoning": "",
    "active_strategy": "none",
    "market_summary": "",
    "portfolio_note": "",
    "watchlist_alerts": [],
    "market_data": {},
    "market_open": False,
    "session_mode": "initializing",
}

# Post-trade review sonucu
_last_review: dict = {
    "status": "Henuz review yapilmadi",
    "timestamp": None,
}

scheduler = BackgroundScheduler(timezone="UTC")


# ─────────────────────────────────────────────────────────────────
# Ana tarama fonksiyonu
# ─────────────────────────────────────────────────────────────────

def run_scan(broker=None, auto_execute: bool = False):
    """
    Tek tarama döngüsü — PIYASA ACIK VEYA KAPALI, HER ZAMAN CALISIR.

    Piyasa kapaliyken:
      - Tarihsel veri analizi yapar
      - Yarinki plan hazirlar
      - Post-trade review yapar
      - Islem tetiklemez (urgency="low")

    Piyasa acikken:
      - Canli veri analizi
      - Islem önerileri (auto_execute'a göre)
    """
    global _last_scan

    market_open = is_market_open()
    premarket   = is_premarket()

    # Session modunu belirle
    if market_open:
        session_mode = "market_open"
    elif premarket:
        session_mode = "pre_market"
    else:
        session_mode = "after_hours"

    print(f"[Scheduler] Tarama basliyor — {datetime.now(timezone.utc).strftime('%H:%M UTC')} | Mod: {session_mode}")

    # 1. Piyasa verisi (her zaman tarihsel veri mevcut)
    market_data = get_market_data()
    if "error" in market_data:
        _last_scan["status"] = f"Veri hatasi: {market_data['error']}"
        _last_scan["timestamp"] = datetime.now(timezone.utc).isoformat()
        _last_scan["session_mode"] = session_mode
        print(f"[Scheduler] Veri hatasi: {market_data['error']}")
        return

    # 2. Portföy durumu
    portfolio = _get_portfolio(broker)

    # 3. Claude karari
    recent = get_recent_trades(limit=20)
    portfolio["pdt_trades_left"] = pdt_trades_left(recent)

    result = run_brain(
        market_data=market_data,
        portfolio=portfolio,
        recent_trades=recent,
        auto_execute=auto_execute and market_open,  # Sadece piyasa acikken execute
    )

    # 4. Bellege kaydet
    _last_scan = {
        "status": "ok",
        "timestamp": result.get("timestamp"),
        "decisions": result.get("decisions", []),
        "regime": result.get("regime", "unknown"),
        "regime_reasoning": result.get("regime_reasoning", ""),
        "active_strategy": result.get("active_strategy", "none"),
        "market_summary": result.get("market_summary", ""),
        "portfolio_note": result.get("portfolio_note", ""),
        "watchlist_alerts": result.get("watchlist_alerts", []),
        "market_data": market_data,
        "market_open": market_open,
        "session_mode": session_mode,
        "auto_execute": auto_execute and market_open,
    }

    # 5. DB'ye logla
    _log_scan(result)

    # 6. Gemini Audit (Council modu — iki AI onaylarsa işlem yapılır)
    #    Gemini başarısız olursa fallback: Claude kararı direkt geçer
    audit_results = []
    gemini_status = "ok"
    try:
        from gemini_auditor import audit_decisions, is_enabled as gemini_enabled
        if gemini_enabled() and result.get("decisions"):
            audit_results = audit_decisions(
                decisions=result.get("decisions", []),
                market_data=market_data,
                portfolio=portfolio,
                regime=result.get("regime", "unknown"),
            )
    except Exception as e:
        gemini_status = "unavailable"
        print(f"[Gemini Audit] Kullanılamıyor (fallback: Claude-only mode): {e}")
        # Fallback: Her karar için AUTO-APPROVE oluştur
        for d in result.get("decisions", []):
            audit_results.append({
                "ticker": d.get("ticker", ""),
                "audit_verdict": "APPROVE",
                "reasoning": "Gemini unavailable — auto-approved by Claude-only fallback",
                "risk_flag": "gemini_offline",
            })

    _last_scan["audit_results"] = audit_results
    _last_scan["gemini_status"] = gemini_status

    # 7. Otomatik islem (sadece piyasa acikken + auto_execute=True)
    if auto_execute and market_open and broker:
        _execute_decisions(result.get("decisions", []), broker, portfolio, market_data, audit_results)

    actionable = [d for d in result.get("decisions", [])
                  if d.get("action") not in ("hold", "watch")]
    print(f"[Scheduler] Tarama tamam | Rejim: {result.get('regime','?')} | "
          f"Strateji: {result.get('active_strategy','?')} | "
          f"{len(actionable)} aksiyon karari")


def run_review(broker=None):
    """Post-trade review — ögrenme döngüsü."""
    global _last_review

    portfolio = _get_portfolio(broker)
    recent = get_recent_trades(limit=20)

    if not recent:
        _last_review = {"status": "Islem gecmisi yok", "timestamp": datetime.now(timezone.utc).isoformat()}
        return

    result = review_past_trades(recent, portfolio)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    _last_review = result

    # DB'ye logla
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    grade TEXT,
                    lessons TEXT,
                    adjustments TEXT
                )
            """)
            conn.execute(
                "INSERT INTO reviews (timestamp, grade, lessons, adjustments) VALUES (?,?,?,?)",
                (
                    result.get("timestamp"),
                    result.get("overall_grade", "?"),
                    json.dumps(result.get("lessons", [])),
                    json.dumps(result.get("strategy_adjustments", [])),
                )
            )
            conn.commit()
    except Exception:
        pass

    print(f"[Scheduler] Post-trade review tamam | Not: {result.get('overall_grade', '?')}")


def get_last_scan() -> dict:
    return _last_scan


def get_last_review() -> dict:
    return _last_review


# ─────────────────────────────────────────────────────────────────
# Scheduler baslat / durdur
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# V5.6: Akilli Zamanlayici (Adaptive Scan Frequency)
# Mod tespit + son tarama zamanina gore skip karar
# ─────────────────────────────────────────────────────────────────

_last_dispatch_time: dict = {"timestamp": None, "mode": None}


def _detect_scan_mode() -> tuple[str, int]:
    """
    Su anki saate gore tarama modu ve interval (dk) dondur.
    NY (America/New_York) saatine gore (DST otomatik).

    Returns: (mode_name, interval_minutes)
    """
    try:
        from pytz import timezone as pytz_tz
        from config import (
            SMART_INTERVAL_MARKET, SMART_INTERVAL_PREMARKET,
            SMART_INTERVAL_AFTERHOURS, SMART_INTERVAL_NIGHT,
            SMART_INTERVAL_WEEKEND,
        )
        ny = datetime.now(pytz_tz('America/New_York'))
        weekday = ny.weekday()  # 0=Mon, 6=Sun
        hour = ny.hour
        minute = ny.minute

        # Hafta sonu (Cumartesi=5, Pazar=6)
        if weekday >= 5:
            return ("weekend", SMART_INTERVAL_WEEKEND)

        # Hafta ici saat dilimleri (NY zamani)
        # Market open: 09:30-16:00 ET
        if (hour == 9 and minute >= 30) or (10 <= hour < 16):
            return ("market_open", SMART_INTERVAL_MARKET)
        # Pre-market: 04:00-09:30 ET
        if 4 <= hour < 9 or (hour == 9 and minute < 30):
            return ("pre_market", SMART_INTERVAL_PREMARKET)
        # After-hours: 16:00-20:00 ET
        if 16 <= hour < 20:
            return ("after_hours", SMART_INTERVAL_AFTERHOURS)
        # Gece: 20:00-04:00 ET
        return ("night", SMART_INTERVAL_NIGHT)

    except Exception as e:
        # Pytz yoksa veya config eksikse, guvenli fallback: her 10 dk
        print(f"[SmartScheduler] Mod tespit hatasi: {e}, fallback 10 dk")
        return ("fallback", 10)


def smart_scan_dispatcher(broker=None, auto_execute: bool = False):
    """
    Her 5 dk tetiklenir, modlara gore SKIP veya RUN karari verir.
    Son tarama zamanina bakar; mod interval'i dolmadan tarama yapmaz.
    """
    global _last_dispatch_time
    mode, interval_min = _detect_scan_mode()

    now = datetime.now(timezone.utc)
    last_ts = _last_dispatch_time.get("timestamp")

    if last_ts is not None:
        elapsed_sec = (now - last_ts).total_seconds()
        if elapsed_sec < (interval_min * 60 - 30):  # 30 sn tolerans
            # Henuz erken, skip
            return

    print(f"[SmartScheduler] Mod: {mode} | Interval: {interval_min}dk | Tarama tetiklendi")
    _last_dispatch_time = {"timestamp": now, "mode": mode}
    run_scan(broker=broker, auto_execute=auto_execute)


def start(broker=None, auto_execute: bool = False, interval_minutes: int = 10):
    """Arka planda zamanlayiciyi baslat."""
    if scheduler.running:
        return

    # Journal DB'yi olustur
    init_journal_db()

    # Pre-market cleanup: bekleyen stale emirleri iptal et
    if broker:
        cleanup = broker.cancel_all_orders()
        print(f"[Startup Cleanup] {cleanup.get('message', '?')}")

    # V5.6: Akilli mod aktif mi?
    try:
        from config import SMART_SCHEDULE_ENABLED
    except ImportError:
        SMART_SCHEDULE_ENABLED = False

    if SMART_SCHEDULE_ENABLED:
        # Akilli mod: her 5 dk dispatcher tetiklenir, mod'a gore skip/run
        scheduler.add_job(
            func=lambda: smart_scan_dispatcher(broker=broker, auto_execute=auto_execute),
            trigger=IntervalTrigger(minutes=5),
            id="market_scan",
            replace_existing=True,
        )
        print("[Scheduler] V5.6: Akilli mod AKTIF (adaptive frequency)")
    else:
        # Eski davranis: her interval_minutes (default 10dk)
        scheduler.add_job(
            func=lambda: run_scan(broker=broker, auto_execute=auto_execute),
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="market_scan",
            replace_existing=True,
        )
        print(f"[Scheduler] Klasik mod: her {interval_minutes}dk")

    # Post-trade review: günde 2 kez
    scheduler.add_job(
        func=lambda: run_review(broker=broker),
        trigger=IntervalTrigger(hours=12),
        id="post_trade_review",
        replace_existing=True,
    )

    # Pre-market cleanup: her gun 13:00 UTC (acilistan 30dk once)
    scheduler.add_job(
        func=lambda: _pre_market_cleanup(broker),
        trigger=IntervalTrigger(hours=24),
        id="pre_market_cleanup",
        replace_existing=True,
    )

    # Ilk taramayi 5 saniye sonra baslat (non-blocking, sunucu hemen acilsin)
    scheduler.add_job(
        func=lambda: run_scan(broker=broker, auto_execute=auto_execute),
        trigger="date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=5),
        id="first_scan",
        replace_existing=True,
    )

    scheduler.start()
    print(f"[Scheduler] V3.1 baslatildi — ilk tarama 5sn sonra, her {interval_minutes}dk tarama + cleanup + review")


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Scheduler] Durduruldu.")


# ─────────────────────────────────────────────────────────────────
# Yardimcilar
# ─────────────────────────────────────────────────────────────────

def _get_portfolio(broker) -> dict:
    """Broker'dan portföy bilgisi al."""
    if broker is None:
        return {"cash": 0, "equity": 0, "positions": []}
    try:
        account   = broker.client.get_account()
        positions = broker.client.get_all_positions()
        return {
            "cash":   float(account.cash),
            "equity": float(account.equity),
            "positions": [
                {
                    "ticker":        p.symbol,
                    "qty":           float(p.qty),
                    "avg_entry":     float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "unrealized_pl": float(p.unrealized_pl),
                }
                for p in positions
            ],
        }
    except Exception as e:
        return {"cash": 0, "equity": 0, "positions": [], "error": str(e)}


def _execute_decisions(decisions: list, broker, portfolio: dict, market_data: dict, audit_results: list = None):
    """
    V4.5: Aksiyon kararlarini Alpaca'ya ilet — Gemini Council onayı ile.
    Claude'un güven skoru + rejime göre dinamik pozisyon boyutlandirma.
    Gemini REJECT ise işlem yapılmaz.
    """
    from risk_manager import RiskManager
    risk = RiskManager(max_risk_pct=0.02)
    equity = portfolio.get("equity", 0)

    # Audit sonuçlarını ticker bazlı indexle
    audit_map = {}
    for a in (audit_results or []):
        audit_map[a.get("ticker", "")] = a

    for d in decisions:
        action     = d.get("action", "hold")
        ticker     = d.get("ticker", "")
        confidence = d.get("confidence", 0)

        # Sadece yüksek güvenli islemler (confidence >= 6)
        if action in ("hold", "watch", "reduce") or not ticker:
            continue
        if confidence < 6:
            print(f"[Auto] {ticker} atlandı — güven skoru düsük ({confidence}/10)")
            continue

        # V4.5: Gemini Council kontrolü
        audit = audit_map.get(ticker)
        if audit:
            verdict = audit.get("audit_verdict", "APPROVE")
            if verdict == "REJECT":
                print(f"[Council] {ticker} REDDEDİLDİ — Gemini: {audit.get('reasoning', '?')}")
                continue
            elif verdict == "MODIFY":
                # Gemini'nin önerdiği parametreleri uygula
                mods = audit.get("modified_params", {})
                if "position_size_pct" in mods:
                    d["position_size_pct"] = mods["position_size_pct"]
                print(f"[Council] {ticker} MODİFİYE — Gemini: {audit.get('reasoning', '?')}")
            else:
                print(f"[Council] {ticker} ONAYLANDI — Gemini + Claude hemfikir")

        try:
            # Piyasa verisinden fiyat ve ATR al
            ticker_data = market_data.get(ticker, {})
            price = ticker_data.get("price", 0)
            atr   = ticker_data.get("atr14", price * 0.02)

            if price <= 0:
                continue

            # ATR bazli stop-loss
            direction = "long" if action in ("long",) else "short"
            stop_price = risk.atr_stop_loss(price, atr, direction, multiplier=1.5)

            # Dinamik pozisyon boyutlandirma
            regime = d.get("strategy", "neutral")  # brain'den gelen rejim bilgisi
            sizing = risk.dynamic_position_size(
                equity=equity,
                entry_price=price,
                stop_loss_price=stop_price,
                confidence=confidence,
                regime=regime,
            )

            qty = sizing.get("qty", 0)
            if qty <= 0:
                continue

            broker.execute(action, ticker, qty, price)
            print(f"[Auto] {action.upper()} {ticker} x{qty} @ ${price:.2f} "
                  f"(confidence={confidence}, risk={sizing.get('risk_pct',0)}%)")

            # E-posta bildirimi gonder
            try:
                audit = audit_map.get(ticker, {})
                send_trade_notification(
                    action=action,
                    ticker=ticker,
                    qty=qty,
                    price=price,
                    confidence=confidence,
                    reasoning=d.get("reasoning", ""),
                    audit_verdict=audit.get("audit_verdict", "APPROVE"),
                    stop_loss=d.get("stop_loss", ""),
                    take_profit=d.get("take_profit", ""),
                    risk_pct=sizing.get("risk_pct", 0),
                )
            except Exception as e:
                print(f"[Notifier] Bildirim hatasi: {e}")
        except Exception as e:
            print(f"[Auto] HATA {ticker}: {e}")


def _pre_market_cleanup(broker):
    """
    Pre-market temizlik: acilistan once tum bekleyen emirleri iptal et.
    Eski/stale emirlerin acilista tetiklenmesini onler.
    """
    if broker is None:
        return
    try:
        # Bekleyen emirleri kontrol et
        pending = broker.get_pending_orders()
        if pending and not any("error" in p for p in pending):
            if len(pending) > 0:
                result = broker.cancel_all_orders()
                print(f"[Pre-Market Cleanup] {result.get('message', '?')}")
            else:
                print("[Pre-Market Cleanup] Bekleyen emir yok, temiz.")
        else:
            print("[Pre-Market Cleanup] Bekleyen emir yok.")
    except Exception as e:
        print(f"[Pre-Market Cleanup] Hata: {e}")


def _log_scan(result: dict):
    """Tarama sonucunu DB'ye kaydet."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    regime TEXT,
                    active_strategy TEXT,
                    decisions TEXT,
                    market_summary TEXT,
                    portfolio_note TEXT
                )
            """)
            conn.execute(
                "INSERT INTO scans (timestamp, regime, active_strategy, decisions, market_summary, portfolio_note) VALUES (?,?,?,?,?,?)",
                (
                    result.get("timestamp"),
                    result.get("regime", ""),
                    result.get("active_strategy", ""),
                    json.dumps(result.get("decisions", [])),
                    result.get("market_summary", ""),
                    result.get("portfolio_note", ""),
                )
            )
            conn.commit()
    except Exception:
        pass
