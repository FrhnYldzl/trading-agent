"""
crypto/auto_executor.py — V5.10-η iskeleti

Brain → Audit → Risk → Broker → (Journal) pipeline orkestrasyonu.

Bu sürümde (skeleton):
  ✓ Pipeline akışı
  ✓ 5 safety gate (daily halt, max positions, cooldown, asset group, min confidence)
  ✓ APScheduler integration (interval-based)
  ✓ Dry-run mode (default — gerçek emir gitmez)
  ✓ Status tracking (last run, next run, gates blocked)
  ⏳ Journal logging (V5.10-ε'da eklenecek)
  ⏳ Gemini audit hook (V5.10-δ'da eklenecek)

Master switch:
  CRYPTO_AUTO_EXECUTE=true env var → scheduler başlar
                     =false (default) → scheduler kapalı, manual run hâlâ çalışır

Broker dry_run ayrı:
  CryptoBroker(dry_run=True) → emir simulasyonu
  CryptoBroker(dry_run=False) → gerçek paper emir
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.asset_class import AssetClass
from crypto.journal import CryptoJournal
from crypto.news_impl import get_sentiment_for_brain
from crypto.anomaly_impl import detect_anomalies


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _isofmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ─────────────────────────────────────────────────────────────────
# Safety gate config — env vars override defaults
# ─────────────────────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try: return int(os.getenv(key, str(default)))
    except: return default


def _env_float(key: str, default: float) -> float:
    try: return float(os.getenv(key, str(default)))
    except: return default


# Paper learning phase muhafazakar default'ları
GATES_DEFAULTS = {
    "MIN_CONFIDENCE": 6,           # Bu değerin altında karar = işlem yok
    "MAX_OPEN_POSITIONS": 3,        # Aynı anda max 3 açık pozisyon
    "DAILY_LOSS_HALT_PCT": -2.0,    # %-2 günlük kayıp → tüm gün halt
    "SYMBOL_COOLDOWN_HOURS": 4,     # Aynı sembol için 4 saat cooldown
    "MAX_NOTIONAL_PER_TRADE": 500,  # Max $500 tek emir notional
    "MAX_GROUP_PCT": 40,            # Tek asset group %40 üst sınır
}


# ─────────────────────────────────────────────────────────────────
# CryptoAutoExecutor
# ─────────────────────────────────────────────────────────────────

class CryptoAutoExecutor:
    """
    Auto-execute pipeline orchestrator.
    Dependency injection: broker, brain, regime, risk, scheduler_helper.
    """

    asset_class = AssetClass.CRYPTO

    def __init__(
        self,
        broker, brain, regime, risk, scheduler_helper,
        data_fetcher, universe,
        asset_group_map: dict,
        cache_get=None, cache_set=None,
        journal: Optional[CryptoJournal] = None,
        auditor=None,  # V5.10-δ: CryptoAuditor (Gemini) — opsiyonel
    ):
        self.broker = broker
        self.brain = brain
        self.regime = regime
        self.risk = risk
        self.scheduler_helper = scheduler_helper
        self.data_fetcher = data_fetcher  # callable: () → market_data dict
        self.universe = universe          # list of symbols
        self.asset_group_map = asset_group_map
        self._cache_get = cache_get
        self._cache_set = cache_set
        # V5.10-ε: journal — auto-init eğer dışarıdan gelmediyse
        self.journal = journal or CryptoJournal()
        # V5.10-δ: Gemini auditor (opsiyonel — None ise audit atlanır)
        self.auditor = auditor

        # Master switch
        self.enabled = (os.getenv("CRYPTO_AUTO_EXECUTE", "false").lower()
                        in ("true", "1", "yes"))

        # Safety gates (override-able via env)
        self.gates = {
            "MIN_CONFIDENCE": _env_int("CRYPTO_MIN_CONFIDENCE",
                                        GATES_DEFAULTS["MIN_CONFIDENCE"]),
            "MAX_OPEN_POSITIONS": _env_int("CRYPTO_MAX_OPEN_POSITIONS",
                                            GATES_DEFAULTS["MAX_OPEN_POSITIONS"]),
            "DAILY_LOSS_HALT_PCT": _env_float("CRYPTO_DAILY_LOSS_HALT_PCT",
                                               GATES_DEFAULTS["DAILY_LOSS_HALT_PCT"]),
            "SYMBOL_COOLDOWN_HOURS": _env_int("CRYPTO_SYMBOL_COOLDOWN_HOURS",
                                              GATES_DEFAULTS["SYMBOL_COOLDOWN_HOURS"]),
            "MAX_NOTIONAL_PER_TRADE": _env_float("CRYPTO_MAX_NOTIONAL_PER_TRADE",
                                                  GATES_DEFAULTS["MAX_NOTIONAL_PER_TRADE"]),
            "MAX_GROUP_PCT": _env_float("CRYPTO_MAX_GROUP_PCT",
                                         GATES_DEFAULTS["MAX_GROUP_PCT"]),
        }

        # Runtime state
        self.last_run: Optional[dict] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self._daily_equity_anchor: Optional[dict] = None  # {date, equity}
        self._last_order_per_symbol: dict[str, datetime] = {}
        self._scheduler: Optional[BackgroundScheduler] = None

    # ───────────────────────────────────────────────────────────
    # Scheduler control
    # ───────────────────────────────────────────────────────────

    def start_scheduler(self) -> dict:
        """APScheduler ile periodic run başlat."""
        if not self.enabled:
            return {"started": False, "reason": "CRYPTO_AUTO_EXECUTE=false"}
        if self._scheduler and self._scheduler.running:
            return {"started": False, "reason": "Already running"}

        mode, interval_min = self.scheduler_helper.detect_scan_mode()

        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._scheduler.add_job(
            self._scheduled_run,
            trigger=IntervalTrigger(minutes=interval_min),
            id="crypto_auto_exec", replace_existing=True,
            next_run_time=_now_utc() + timedelta(seconds=10),
        )
        self._scheduler.start()
        self.next_run = _now_utc() + timedelta(seconds=10)
        return {"started": True, "mode": mode, "interval_min": interval_min}

    def stop_scheduler(self) -> dict:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            self.next_run = None
            return {"stopped": True}
        return {"stopped": False, "reason": "Not running"}

    def _scheduled_run(self):
        """APScheduler callback — run_once'ı sarmalar, next_run'ı günceller."""
        try:
            self.run_once()
        finally:
            mode, interval_min = self.scheduler_helper.detect_scan_mode()
            self.next_run = _now_utc() + timedelta(minutes=interval_min)

    # ───────────────────────────────────────────────────────────
    # MAIN PIPELINE
    # ───────────────────────────────────────────────────────────

    def run_once(self, force: bool = False) -> dict:
        """
        Tek bir tarama döngüsü.

        Pipeline:
          1. Pre-flight: daily halt, account ok?
          2. Market data + regime
          3. Brain reasoning
          4. (Gemini audit — V5.10-δ'da eklenecek)
          5. Per-decision gates: min confidence, cooldown, position count, asset group
          6. Risk-adjusted position size
          7. Broker.execute (broker dry_run'a bağlı)
          8. Journal log (V5.10-ε): brain_run + trade_open + gate_block + error
          9. Result summary, runtime state güncelle
        """
        # V5.10-ε: Her run benzersiz UUID ile takip edilir, journal entries
        # bu UUID üzerinden timeline'a bağlanabilir.
        pipeline_run_id = str(uuid.uuid4())[:8]

        result = {
            "timestamp": _isofmt(_now_utc()),
            "pipeline_run_id": pipeline_run_id,
            "force": force,
            "decisions_total": 0,
            "decisions_executed": 0,
            "decisions_blocked": 0,
            "blocked_by_gate": {},
            "errors": [],
            "regime": None,
            "strategy": None,
            "broker_dry_run": getattr(self.broker, "dry_run", True),
            "summary": "",
        }

        # 1. Pre-flight
        try:
            account = self.broker.get_account_status()
            equity = account.get("equity", 0)
            self._update_daily_anchor(equity)
        except Exception as e:
            result["errors"].append(f"account fetch: {e}")
            result["summary"] = "Pre-flight failed"
            try:
                self.journal.log_error(pipeline_run_id, f"account fetch: {e}")
            except Exception: pass
            self.last_run = result
            self.run_count += 1
            return result

        # Daily halt gate
        halt_check = self._check_daily_halt(equity)
        if halt_check["blocked"]:
            result["blocked_by_gate"]["daily_halt"] = halt_check["reason"]
            result["summary"] = f"DAILY HALT: {halt_check['reason']}"
            self.last_run = result
            self.run_count += 1
            return result

        # 2. Data + regime (cache aware)
        try:
            md = self.data_fetcher()
            regime = self.regime.detect(md)
            result["regime"] = regime.get("regime")
        except Exception as e:
            result["errors"].append(f"data/regime: {e}")
            result["summary"] = "Data/regime fetch failed"
            self.last_run = result
            self.run_count += 1
            return result

        # ━━━ V5.10-η.4: Trade Close Lifecycle ━━━
        # Açık trade'leri tara — stop/TP hit olanları kapat, manuel kapananları
        # journal'a yansıt. Bu adım brain'den ÖNCE — yeni karar verirken
        # güncel pozisyon durumunu görmeli.
        try:
            close_summary = self._check_exits_and_close(md, pipeline_run_id)
            result["closes_processed"] = close_summary
        except Exception as e:
            result["errors"].append(f"close_lifecycle: {e}")

        # ━━━ V5.10-γ: Anomaly Detection ━━━
        # Brain'den önce — kritik anomali varsa emergency_halt set ederiz
        # ve yeni LONG kararı engelleriz (close_long ya da reduce serbest).
        anomaly_state = {"emergency_halt": False, "anomalies": []}
        try:
            anomaly_state = detect_anomalies(md)
            result["anomalies"] = anomaly_state
            if anomaly_state.get("emergency_halt"):
                # Critical (BTC flash dump vs.) — yeni long bloke
                # Mevcut pozisyonların close_long işlemi yapılabilir
                pass  # gate'lerde uygulanacak
        except Exception as e:
            result["errors"].append(f"anomaly: {e}")

        # ━━━ V5.10-β: News + Sentiment ━━━
        sentiment_data = None
        try:
            sentiment_data = get_sentiment_for_brain(list(self.universe))
            if sentiment_data:
                result["news_summary"] = {
                    "tickers_with_news": len(sentiment_data),
                    "tickers": list(sentiment_data.keys()),
                }
        except Exception as e:
            result["errors"].append(f"news: {e}")
            sentiment_data = None

        # 3. Brain
        brain_run_id: Optional[int] = None
        try:
            portfolio = self._get_portfolio()
            brain_out = self.brain.run_brain(
                market_data=md, portfolio=portfolio,
                regime=regime, recent_trades=[],
                sentiment=sentiment_data,  # V5.10-β: news context
                learning_context=None,
            )
            result["strategy"] = brain_out.get("active_strategy")
            decisions = brain_out.get("decisions", [])
            result["decisions_total"] = len(decisions)
            # V5.10-ε: Brain run kaydı (journal'a)
            try:
                brain_run_id = self.journal.log_brain_run(
                    pipeline_run_id=pipeline_run_id,
                    regime=regime,
                    strategy=result["strategy"],
                    market_snapshot=md,
                    decisions=decisions,
                    summary=brain_out.get("market_summary", ""),
                )
            except Exception as je:
                result["errors"].append(f"journal brain_run: {je}")
        except Exception as e:
            result["errors"].append(f"brain: {e}")
            result["summary"] = f"Brain error: {e}"
            try: self.journal.log_error(pipeline_run_id, f"brain: {e}")
            except Exception: pass
            self.last_run = result
            self.run_count += 1
            return result

        # 4. Gemini audit (V5.10-δ) — opsiyonel, async olmasa da hızlı
        audit_results: list[dict] = []
        if self.auditor and getattr(self.auditor, "enabled", False):
            try:
                audit_results = self.auditor.audit_decisions(
                    decisions=decisions, market_data=md,
                    portfolio=portfolio,
                    regime=regime.get("regime", "unknown"),
                )
                # Audit verdict'lerini decision'lara enjekte et + journal'a yaz
                audit_by_ticker = {a["ticker"]: a for a in audit_results}
                for d in decisions:
                    a = audit_by_ticker.get(d.get("ticker"))
                    if a:
                        d["audit"] = a
                        try:
                            self.journal.log_audit(
                                pipeline_run_id=pipeline_run_id,
                                brain_run_id=brain_run_id,
                                symbol=d.get("ticker"),
                                audit_verdict=a.get("audit_verdict", "?"),
                                audit_note=a.get("reasoning", ""),
                            )
                        except Exception: pass
            except Exception as e:
                result["errors"].append(f"audit: {e}")
                try: self.journal.log_error(pipeline_run_id, f"audit: {e}")
                except Exception: pass

        # Audit-blocked sayacı
        audit_rejects = 0

        # 5+6+7. Per-decision gates → size → execute
        positions_now = portfolio.get("positions", [])
        # ⚡ V5.10-η.3 fix: bu run sırasında execute edilen "pending" pozisyonları
        # da gate kontrolünde say. Önceki bug: 6 LONG hepsi gate'i geçiyordu çünkü
        # gate kontrolü sadece run BAŞINDAKİ pozisyon sayısına bakıyordu.
        pending_executions: list[dict] = []
        for d in decisions:
            ticker = d.get("ticker", "?")
            action = (d.get("action") or "").lower()

            # Sadece long/close actions sürer; hold/watch ignore
            if action not in ("long", "close_long", "reduce"):
                continue

            # ━━━ V5.10-γ: ANOMALY EMERGENCY HALT GATE ━━━
            # Critical anomali varsa (BTC flash dump vs.) yeni LONG bloke,
            # ama close_long ve reduce serbest (pozisyon kapatma izni).
            if anomaly_state.get("emergency_halt") and action == "long":
                halt_reason = anomaly_state.get("summary", "Anomaly emergency halt")
                result["blocked_by_gate"][ticker] = halt_reason
                result["decisions_blocked"] += 1
                try:
                    self.journal.log_gate_block(
                        pipeline_run_id=pipeline_run_id,
                        brain_run_id=brain_run_id,
                        symbol=ticker, action=action,
                        confidence=int(d.get("confidence", 0)),
                        blocked_reason=halt_reason,
                        asset_group=(d.get("asset_group")
                                     or self.asset_group_map.get(ticker, "Unknown")),
                    )
                except Exception: pass
                continue

            # ━━━ V5.10-δ: AUDIT GATE ━━━
            # Audit yapıldıysa ve REJECT verdict'i varsa, gate'lere girmeden bloke
            audit = d.get("audit")
            if audit and audit.get("audit_verdict") == "REJECT":
                reject_reason = audit.get("reasoning", "Gemini audit rejected")
                flags = ", ".join(audit.get("risk_flags", []))
                full_reason = f"Gemini REJECT: {reject_reason} [{flags}]"
                result["blocked_by_gate"][ticker] = full_reason
                result["decisions_blocked"] += 1
                audit_rejects += 1
                try:
                    self.journal.log_gate_block(
                        pipeline_run_id=pipeline_run_id,
                        brain_run_id=brain_run_id,
                        symbol=ticker, action=action,
                        confidence=int(d.get("confidence", 0)),
                        blocked_reason=full_reason,
                        asset_group=(d.get("asset_group")
                                     or self.asset_group_map.get(ticker, "Unknown")),
                    )
                except Exception: pass
                continue

            # Audit MODIFY → brain'in stop/TP/size'ı audit önerisiyle değiştir
            if audit and audit.get("audit_verdict") == "MODIFY":
                mods = audit.get("modified_params", {})
                if "stop_loss" in mods:
                    d["stop_loss"] = mods["stop_loss"]
                if "take_profit" in mods:
                    d["take_profit"] = mods["take_profit"]
                if "position_size_pct" in mods:
                    d["position_size_pct"] = mods["position_size_pct"]
                # MODIFY uygulandı, ama yine de gate'lere giriyor

            # Per-decision gate stack (mevcut + bu run'da pending olanları say)
            gate_block = self._check_decision_gates(
                d, positions_now, pending_executions, equity,
            )
            if gate_block:
                result["blocked_by_gate"][ticker] = gate_block
                result["decisions_blocked"] += 1
                # V5.10-ε: Journal log
                try:
                    self.journal.log_gate_block(
                        pipeline_run_id=pipeline_run_id,
                        brain_run_id=brain_run_id,
                        symbol=ticker, action=action,
                        confidence=int(d.get("confidence", 0)),
                        blocked_reason=gate_block,
                        asset_group=(
                            d.get("asset_group")
                            or self.asset_group_map.get(ticker, "Unknown")
                        ),
                    )
                except Exception: pass
                continue

            # Position size (risk_impl)
            try:
                # Brain entry zone'undan tek fiyat çıkar (orta nokta, basit)
                entry = self._parse_price(d.get("entry_zone")) or md.get(ticker, {}).get("price", 0)
                stop = self._parse_price(d.get("stop_loss"))
                if entry > 0 and stop and stop > 0:
                    sizing = self.risk.dynamic_position_size(
                        equity=equity, entry_price=entry, stop_loss_price=stop,
                        confidence=int(d.get("confidence", 5)),
                        regime=regime.get("regime", "neutral"),
                    )
                else:
                    sizing = {"qty": 0, "error": "invalid entry/stop"}
            except Exception as e:
                result["errors"].append(f"sizing {ticker}: {e}")
                continue

            # Notional cap gate
            notional = (sizing.get("position_value") or 0)
            if notional > self.gates["MAX_NOTIONAL_PER_TRADE"]:
                # Notional cap'e indir
                cap = self.gates["MAX_NOTIONAL_PER_TRADE"]
                sizing["qty"] = max(0, cap / entry) if entry > 0 else 0
                sizing["position_value"] = cap
                sizing["notional_capped"] = True

            # 7. Execute (dry_run kontrolü broker'da)
            try:
                exec_result = self.broker.execute(
                    action=action, ticker=ticker,
                    qty=sizing.get("qty", 0), price=entry,
                    stop_loss=stop,
                    take_profit=self._parse_price(d.get("take_profit")),
                    order_type="market",
                )
                d["execution"] = exec_result
                d["sizing"] = sizing
                # V5.10.1 fix: Alpaca'nın "new", "accepted", "submitted",
                # "pending_new", "partially_filled" gibi statüleri de "executed"
                # sayar. Önceki kod sadece "filled" / "pending" / "dry_run"'a
                # bakıyordu → real Alpaca order'ları pending listesine eklenmiyordu
                # → max positions gate her sefer 0 görüyordu → 6 LONG açıldı.
                exec_status = (exec_result.get("status") or "").lower()
                rejected_statuses = ("error", "rejected", "canceled", "expired", "rejected_new")
                if exec_status not in rejected_statuses:
                    result["decisions_executed"] += 1
                    self._last_order_per_symbol[ticker] = _now_utc()
                    # ⚡ V5.10-η.3: Pending listesine ekle ki sonraki kararlarda gate sayar
                    pending_executions.append({
                        "symbol": ticker,
                        "market_value": sizing.get("position_value", 0),
                        "asset_group": (
                            d.get("asset_group")
                            or self.asset_group_map.get(ticker, "Unknown")
                        ),
                        "qty": sizing.get("qty", 0),
                        "_pending": True,
                    })
                    # V5.10-ε: Journal log trade_open
                    try:
                        self.journal.log_trade_open(
                            pipeline_run_id=pipeline_run_id,
                            brain_run_id=brain_run_id,
                            symbol=ticker, action=action,
                            qty=sizing.get("qty", 0),
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=self._parse_price(d.get("take_profit")),
                            confidence=int(d.get("confidence", 0)),
                            asset_group=(
                                d.get("asset_group")
                                or self.asset_group_map.get(ticker, "Unknown")
                            ),
                            strategy=d.get("strategy"),
                            regime=regime.get("regime"),
                            execution_status=exec_result.get("status", "unknown"),
                            reasoning=d.get("reasoning", ""),
                        )
                    except Exception as je:
                        result["errors"].append(f"journal trade_open {ticker}: {je}")
                else:
                    result["decisions_blocked"] += 1
                    result["blocked_by_gate"][ticker] = (
                        f"broker rejected: {exec_result.get('reason', 'unknown')}"
                    )
            except Exception as e:
                result["errors"].append(f"execute {ticker}: {e}")

        # 8. (Journal — V5.10-ε)
        # journal.log_brain_run(brain_out, regime, md, result)

        # 9. Summary
        audit_summary = ""
        if audit_results:
            approved = sum(1 for a in audit_results if a.get("audit_verdict") == "APPROVE")
            modified = sum(1 for a in audit_results if a.get("audit_verdict") == "MODIFY")
            audit_summary = (
                f" Gemini audit: {approved} onay, {audit_rejects} red, "
                f"{modified} modify."
            )
            result["audit"] = {
                "total": len(audit_results),
                "approved": approved,
                "rejected": audit_rejects,
                "modified": modified,
                "results": audit_results,
            }
        result["summary"] = (
            f"{result['decisions_total']} kararın "
            f"{result['decisions_executed']}'i execute, "
            f"{result['decisions_blocked']}'i bloke. "
            f"Strategy: {result['strategy']}, Regime: {result['regime']}."
            f"{audit_summary}"
        )
        # Tam karar dökümünü saklamayalım (memory) — özet yeter
        result["decisions"] = [
            {
                "ticker": d.get("ticker"),
                "action": d.get("action"),
                "confidence": d.get("confidence"),
                "executed": "execution" in d,
                "execution_status": d.get("execution", {}).get("status"),
                "sizing_qty": d.get("sizing", {}).get("qty"),
                "sizing_value": d.get("sizing", {}).get("position_value"),
            }
            for d in decisions
        ]

        self.last_run = result
        self.run_count += 1
        return result

    # ───────────────────────────────────────────────────────────
    # Safety gates
    # ───────────────────────────────────────────────────────────

    def _update_daily_anchor(self, equity: float):
        today = _now_utc().date().isoformat()
        if not self._daily_equity_anchor or self._daily_equity_anchor.get("date") != today:
            self._daily_equity_anchor = {"date": today, "equity": equity}

    def _check_daily_halt(self, equity: float) -> dict:
        if not self._daily_equity_anchor:
            return {"blocked": False}
        anchor = self._daily_equity_anchor.get("equity", 0)
        if anchor <= 0:
            return {"blocked": False}
        change_pct = (equity - anchor) / anchor * 100
        if change_pct <= self.gates["DAILY_LOSS_HALT_PCT"]:
            return {
                "blocked": True,
                "reason": f"Günlük kayıp %{change_pct:.2f}, halt eşiği %{self.gates['DAILY_LOSS_HALT_PCT']}",
                "current_pct": round(change_pct, 2),
            }
        return {"blocked": False, "current_pct": round(change_pct, 2)}

    def _check_decision_gates(
        self, decision: dict, positions: list,
        pending_executions: list, equity: float,
    ) -> Optional[str]:
        """
        Gate kontrolü. positions = mevcut açık pozisyonlar.
        pending_executions = bu run sırasında execute edilenler (intra-run sayım).

        ⚡ V5.10-η.3 fix: max_positions ve group_concentration gate'leri
        artık intra-run pending'leri de hesaba katıyor.
        """
        ticker = decision.get("ticker", "?")
        action = (decision.get("action") or "").lower()
        confidence = int(decision.get("confidence", 0))

        # Mevcut + pending = bu kararın "öncesinde" portföyde olacak şey
        all_held = list(positions) + list(pending_executions)

        # Gate 1: Min confidence
        if confidence < self.gates["MIN_CONFIDENCE"]:
            return f"confidence {confidence} < {self.gates['MIN_CONFIDENCE']}"

        # Gate 2: Max open positions (mevcut + pending)
        if action == "long":
            # Aynı sembol pozisyonu varsa "yeni" sayılmıyor (add-on durumu)
            distinct_symbols = {p.get("symbol") for p in all_held if p.get("symbol") != ticker}
            existing_count = len(distinct_symbols)
            if existing_count >= self.gates["MAX_OPEN_POSITIONS"]:
                return (
                    f"max positions reached "
                    f"({existing_count}/{self.gates['MAX_OPEN_POSITIONS']} "
                    f"{'mevcut+pending' if pending_executions else 'mevcut'})"
                )

        # Gate 3: Same-symbol cooldown
        last = self._last_order_per_symbol.get(ticker)
        if last:
            elapsed_h = (_now_utc() - last).total_seconds() / 3600
            if elapsed_h < self.gates["SYMBOL_COOLDOWN_HOURS"]:
                remaining = self.gates["SYMBOL_COOLDOWN_HOURS"] - elapsed_h
                return f"cooldown {remaining:.1f}h kaldı"

        # Gate 4: Asset group concentration (mevcut + pending)
        if action == "long" and equity > 0:
            group = decision.get("asset_group") or self.asset_group_map.get(ticker, "Unknown")
            current_group_value = sum(
                p.get("market_value", 0) for p in all_held
                if (p.get("asset_group")
                    or self.asset_group_map.get(p.get("symbol", ""), "Unknown")) == group
            )
            current_group_pct = current_group_value / equity * 100
            if current_group_pct >= self.gates["MAX_GROUP_PCT"]:
                return (
                    f"group {group} %{current_group_pct:.1f} "
                    f"≥ %{self.gates['MAX_GROUP_PCT']} cap "
                    f"({'pending dahil' if pending_executions else 'mevcut'})"
                )

        return None  # tüm gate'ler geçti

    # ───────────────────────────────────────────────────────────
    # Helpers
    # ───────────────────────────────────────────────────────────

    def _get_portfolio(self) -> dict:
        try:
            account = self.broker.get_account_status()
            positions_raw = self.broker.client.get_all_positions()
            crypto_positions = [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price) if p.current_price else None,
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "asset_group": self.asset_group_map.get(p.symbol, "Unknown"),
                }
                for p in positions_raw
                if p.asset_class and "crypto" in str(p.asset_class).lower()
            ]
            return {
                "cash": account.get("cash", 0),
                "equity": account.get("equity", 0),
                "positions": crypto_positions,
            }
        except Exception:
            return {"cash": 0, "equity": 0, "positions": []}

    # ───────────────────────────────────────────────────────────
    # V5.10-η.4: Trade Close Lifecycle
    # ───────────────────────────────────────────────────────────

    def _check_exits_and_close(self, market_data: dict, pipeline_run_id: str) -> dict:
        """
        Açık trade'lerde stop/TP hit olduysa kapat, manuel kapananları yansıt.

        Returns: özet dict (stop_hit, tp_hit, manual_close, errors sayıları)
        """
        summary = {"stop_hit": 0, "tp_hit": 0, "manual_close": 0, "errors": 0}

        # 1. Journal'daki açık trade'ler
        try:
            open_trades = self.journal.get_open_trades()
        except Exception:
            return summary
        if not open_trades:
            return summary

        # 2. Alpaca'daki şu anki crypto pozisyonları (market value, qty)
        try:
            alpaca_positions = self.broker.client.get_all_positions()
            alpaca_crypto = {
                # Slash form ve slash-siz form'u eşleştir
                self._normalize_symbol(p.symbol): p
                for p in alpaca_positions
                if p.asset_class and "crypto" in str(p.asset_class).lower()
            }
        except Exception:
            alpaca_crypto = {}

        # 3. Her açık trade için:
        for trade in open_trades:
            symbol = trade.get("symbol")
            if not symbol:
                continue
            symbol_norm = self._normalize_symbol(symbol)
            entry_price = trade.get("entry_price") or 0
            qty = trade.get("qty") or 0
            stop = trade.get("stop_loss")
            tp = trade.get("take_profit")
            trade_open_id = trade.get("id")

            current_data = market_data.get(symbol, {})
            current_price = current_data.get("price")

            # Pozisyon Alpaca'da yoksa = manuel kapanmış (kullanıcı veya başka)
            if symbol_norm not in alpaca_crypto:
                # Manual close: P&L'ı bilmediğimiz için current_price kullan
                if current_price:
                    self._log_close(
                        trade_open_id, symbol, entry_price, current_price,
                        qty, "manual_close", pipeline_run_id,
                    )
                    summary["manual_close"] += 1
                continue

            # Stop hit?
            if current_price and stop and current_price <= stop:
                close_result = self.broker.execute(
                    action="close_long", ticker=symbol,
                    qty=qty, price=current_price,
                )
                if close_result.get("status") not in ("error", "rejected"):
                    self._log_close(
                        trade_open_id, symbol, entry_price, current_price,
                        qty, "stop_hit", pipeline_run_id,
                    )
                    summary["stop_hit"] += 1
                else:
                    summary["errors"] += 1
                continue

            # TP hit?
            if current_price and tp and current_price >= tp:
                close_result = self.broker.execute(
                    action="close_long", ticker=symbol,
                    qty=qty, price=current_price,
                )
                if close_result.get("status") not in ("error", "rejected"):
                    self._log_close(
                        trade_open_id, symbol, entry_price, current_price,
                        qty, "tp_hit", pipeline_run_id,
                    )
                    summary["tp_hit"] += 1
                else:
                    summary["errors"] += 1
                continue

        return summary

    def _log_close(
        self, trade_open_id, symbol, entry_price, exit_price, qty,
        exit_reason: str, pipeline_run_id: str,
    ):
        """Journal'a trade_close kaydı + P&L hesabı."""
        try:
            # Hold süresi: trade_open timestamp'inden şimdi
            self.journal.log_trade_close(
                trade_open_id=trade_open_id,
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                qty=qty,
                exit_reason=exit_reason,
                hold_minutes=None,  # Hesabı için ek query gerekir; opsiyonel
            )
        except Exception as e:
            print(f"[CryptoAutoExec] log_close error: {e}")

    @staticmethod
    def _normalize_symbol(sym: str) -> str:
        """BTC/USD ve BTCUSD form'larını eşitle."""
        s = (sym or "").upper().replace("/", "")
        return s

    @staticmethod
    def _parse_price(s) -> Optional[float]:
        """Brain'den gelen fiyat string'i ('77800-78500', '74800', vs.) → tek float."""
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return float(s)
        try:
            txt = str(s).replace("$", "").replace(",", "").strip()
            if "-" in txt:
                parts = txt.split("-")
                a, b = float(parts[0]), float(parts[1])
                return (a + b) / 2
            return float(txt)
        except Exception:
            return None

    # ───────────────────────────────────────────────────────────
    # Status reporting
    # ───────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "asset_class": "crypto",
            "auto_execute_enabled": self.enabled,
            "scheduler_running": bool(self._scheduler and self._scheduler.running),
            "broker_dry_run": getattr(self.broker, "dry_run", True),
            "broker_paper": getattr(self.broker, "paper", True),
            "run_count": self.run_count,
            "last_run": self.last_run,
            "next_run": _isofmt(self.next_run),
            "gates": self.gates,
            "daily_anchor": self._daily_equity_anchor,
            "cooldowns": {
                t: _isofmt(dt)
                for t, dt in self._last_order_per_symbol.items()
            },
        }
