"""
crypto/journal.py — V5.10-ε: Crypto trade journal (seyir defteri).

Auto-executor'ın her aşamasını SQLite'a kaydeder:
  - brain_run: Claude AI tarama, regime, decisions snapshot
  - audit:     (V5.10-δ'da) Gemini denetimi
  - trade_open: Pozisyon açılış (entry, stop, TP, sizing)
  - trade_close: Pozisyon kapanış (exit, P&L, hold süresi)
  - gate_block: Bir kararın gate tarafından bloke edilmesi
  - error:      Pipeline hataları
  - lesson:     Periyodik öğrenilen dersler (Claude review)

Tasarım kararları:
  - SQLite (tek dosya, ek bağımlılık yok)
  - Equity'nin trade_journal.py'sından AYRI (asset_class izolasyonu)
  - JSON kolonları: snapshot (market_data), decisions, audit_verdict
  - Indexed: timestamp, event_type, symbol — hızlı filter/aggregate
  - Sonradan analiz için kapsamlı: regime'ı/asset_group'u/confidence'ı kaydeder

Kullanım:
    from crypto.journal import CryptoJournal
    j = CryptoJournal(db_path="crypto_journal.db")
    j.log_brain_run(regime, market_snapshot, decisions, summary)
    j.log_trade_open(symbol, qty, entry_price, ...)
    entries = j.get_recent(limit=100)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def _resolve_db_path() -> str:
    """
    DB yolunu çöz — Railway Volume desteği:

    1. JOURNAL_DB_PATH env var → set edilmişse onu kullan (Railway override)
    2. /app/data/crypto_journal.db → varsa (Railway Volume mount path)
    3. server/crypto_journal.db → lokal fallback (Volume yok)

    Railway Volume kullanımı:
      Service → Settings → Volumes → + New Volume
      Mount path: /app/data
      Bu sayede SQLite dosyası container redeploy'larını survive eder.
    """
    env_path = os.getenv("JOURNAL_DB_PATH")
    if env_path:
        return env_path
    railway_volume = Path("/app/data")
    if railway_volume.is_dir() or railway_volume.parent.is_dir():
        try:
            railway_volume.mkdir(parents=True, exist_ok=True)
            return str(railway_volume / "crypto_journal.db")
        except Exception:
            pass
    # Lokal fallback
    return str(Path(__file__).parent.parent / "crypto_journal.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    asset_class     TEXT NOT NULL DEFAULT 'crypto',
    symbol          TEXT,
    -- Brain context
    regime          TEXT,
    strategy        TEXT,
    confidence      INTEGER,
    asset_group     TEXT,
    -- Trade
    action          TEXT,
    qty             REAL,
    entry_price     REAL,
    stop_loss       REAL,
    take_profit     REAL,
    exit_price      REAL,
    pnl_dollar      REAL,
    pnl_pct         REAL,
    hold_minutes    INTEGER,
    -- References
    brain_run_id    INTEGER,
    trade_open_id   INTEGER,
    -- Audit (V5.10-δ)
    audit_verdict   TEXT,    -- approved / rejected / warned
    audit_note      TEXT,
    -- Pipeline
    pipeline_run_id TEXT,    -- her run için UUID-benzeri
    blocked_reason  TEXT,
    error_message   TEXT,
    -- Snapshots (JSON)
    market_snapshot TEXT,    -- JSON: o anki market_data özeti
    decisions_json  TEXT,    -- JSON: brain_run'da tüm decisions
    metadata_json   TEXT,    -- JSON: ek bilgi (free-form)
    summary         TEXT
);

CREATE INDEX IF NOT EXISTS idx_journal_ts ON journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_journal_event ON journal(event_type);
CREATE INDEX IF NOT EXISTS idx_journal_symbol ON journal(symbol);
CREATE INDEX IF NOT EXISTS idx_journal_run ON journal(pipeline_run_id);
"""


# ─────────────────────────────────────────────────────────────────
# Journal class
# ─────────────────────────────────────────────────────────────────

class CryptoJournal:
    """SQLite-backed crypto trade journal."""

    def __init__(self, db_path: str = None):
        """
        db_path verilmezse otomatik çözüm:
          1. JOURNAL_DB_PATH env var (Railway override)
          2. /app/data/crypto_journal.db (Railway Volume mount)
          3. server/crypto_journal.db (lokal fallback)
        """
        if db_path is None:
            self.db_path = _resolve_db_path()
        else:
            p = Path(db_path)
            if not p.is_absolute():
                p = Path(__file__).parent.parent / db_path
            self.db_path = str(p)
        # DB dizinini oluştur (varsa no-op)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self):
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ───────────────────────────────────────────────────────
    # Logging
    # ───────────────────────────────────────────────────────

    def _insert(self, **kwargs) -> int:
        """Generic insert. timestamp default şimdi."""
        kwargs.setdefault("timestamp", _now_iso())
        kwargs.setdefault("asset_class", "crypto")
        cols = list(kwargs.keys())
        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT INTO journal ({','.join(cols)}) VALUES ({placeholders})"
        with self._conn() as c:
            cur = c.execute(sql, [kwargs[k] for k in cols])
            return cur.lastrowid

    def log_brain_run(
        self, pipeline_run_id: str, regime: dict, strategy: str,
        market_snapshot: dict, decisions: list, summary: str = "",
    ) -> int:
        """Tüm brain çıktısını + market state'i kaydet."""
        # Market snapshot küçült (sadece anahtar fiyatlar + indikatörler)
        compact_snapshot = {
            sym: {
                "price": d.get("price"),
                "change_pct": d.get("change_pct"),
                "rsi14": d.get("rsi14"),
                "atr_pct": d.get("atr_pct"),
                "trend": d.get("trend"),
                "momentum_score": d.get("momentum_score"),
            }
            for sym, d in (market_snapshot or {}).items()
            if not sym.startswith("_") and "error" not in d
        }
        return self._insert(
            event_type="brain_run",
            pipeline_run_id=pipeline_run_id,
            regime=regime.get("regime") if isinstance(regime, dict) else regime,
            strategy=strategy,
            market_snapshot=json.dumps(compact_snapshot),
            decisions_json=json.dumps(decisions or []),
            summary=summary,
        )

    def log_trade_open(
        self, pipeline_run_id: str, brain_run_id: Optional[int],
        symbol: str, action: str, qty: float, entry_price: float,
        stop_loss: float = None, take_profit: float = None,
        confidence: int = None, asset_group: str = None,
        strategy: str = None, regime: str = None,
        execution_status: str = "dry_run",
        reasoning: str = "",
    ) -> int:
        """Pozisyon açılışını logla."""
        return self._insert(
            event_type="trade_open",
            pipeline_run_id=pipeline_run_id,
            brain_run_id=brain_run_id,
            symbol=symbol, action=action,
            qty=qty, entry_price=entry_price,
            stop_loss=stop_loss, take_profit=take_profit,
            confidence=confidence, asset_group=asset_group,
            strategy=strategy, regime=regime,
            metadata_json=json.dumps({
                "execution_status": execution_status,
                "reasoning": reasoning,
            }),
        )

    def log_trade_close(
        self, trade_open_id: int, symbol: str,
        entry_price: float, exit_price: float, qty: float,
        exit_reason: str = "manual", hold_minutes: int = None,
    ) -> int:
        """Pozisyon kapanışını logla, P&L hesapla."""
        pnl_dollar = (exit_price - entry_price) * qty
        pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        return self._insert(
            event_type="trade_close",
            trade_open_id=trade_open_id,
            symbol=symbol,
            entry_price=entry_price, exit_price=exit_price, qty=qty,
            pnl_dollar=round(pnl_dollar, 2), pnl_pct=round(pnl_pct, 2),
            hold_minutes=hold_minutes,
            metadata_json=json.dumps({"exit_reason": exit_reason}),
        )

    def log_gate_block(
        self, pipeline_run_id: str, brain_run_id: Optional[int],
        symbol: str, action: str, confidence: int,
        blocked_reason: str, asset_group: str = None,
    ) -> int:
        return self._insert(
            event_type="gate_block",
            pipeline_run_id=pipeline_run_id, brain_run_id=brain_run_id,
            symbol=symbol, action=action, confidence=confidence,
            blocked_reason=blocked_reason, asset_group=asset_group,
        )

    def log_audit(
        self, pipeline_run_id: str, brain_run_id: Optional[int],
        symbol: str, audit_verdict: str, audit_note: str = "",
    ) -> int:
        """V5.10-δ Gemini audit kaydı."""
        return self._insert(
            event_type="audit",
            pipeline_run_id=pipeline_run_id, brain_run_id=brain_run_id,
            symbol=symbol,
            audit_verdict=audit_verdict, audit_note=audit_note,
        )

    def log_error(
        self, pipeline_run_id: str, error_message: str,
        symbol: str = None,
    ) -> int:
        return self._insert(
            event_type="error",
            pipeline_run_id=pipeline_run_id,
            symbol=symbol, error_message=error_message,
        )

    # ───────────────────────────────────────────────────────
    # Query helpers
    # ───────────────────────────────────────────────────────

    def get_recent(self, limit: int = 100, event_type: str = None,
                   symbol: str = None) -> list[dict]:
        """Son N kayıt, filtre opsiyonel."""
        sql = "SELECT * FROM journal WHERE 1=1"
        params: list = []
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_by_pipeline_run(self, pipeline_run_id: str) -> list[dict]:
        """Tek bir run'ın tüm event'leri (timeline view için)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM journal WHERE pipeline_run_id = ? ORDER BY id",
                [pipeline_run_id],
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_open_trades(self) -> list[dict]:
        """trade_open olup henüz trade_close olmamış kayıtlar."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM journal
                WHERE event_type = 'trade_open'
                  AND id NOT IN (
                    SELECT trade_open_id FROM journal
                    WHERE event_type = 'trade_close' AND trade_open_id IS NOT NULL
                  )
                ORDER BY id DESC
            """).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_performance(self, days: int = 30) -> dict:
        """Aggregate stats — son N gün."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as c:
            # Closed trades
            closed = c.execute("""
                SELECT pnl_dollar, pnl_pct, hold_minutes, symbol, asset_group
                FROM journal
                WHERE event_type = 'trade_close' AND timestamp > ?
            """, [cutoff]).fetchall()
            closed = [dict(r) for r in closed]
            # Brain runs
            brain_count = c.execute(
                "SELECT COUNT(*) FROM journal WHERE event_type = 'brain_run' AND timestamp > ?",
                [cutoff],
            ).fetchone()[0]
            # Gate blocks
            block_count = c.execute(
                "SELECT COUNT(*) FROM journal WHERE event_type = 'gate_block' AND timestamp > ?",
                [cutoff],
            ).fetchone()[0]
            # Errors
            err_count = c.execute(
                "SELECT COUNT(*) FROM journal WHERE event_type = 'error' AND timestamp > ?",
                [cutoff],
            ).fetchone()[0]

        wins = [t for t in closed if (t.get("pnl_dollar") or 0) > 0]
        losses = [t for t in closed if (t.get("pnl_dollar") or 0) < 0]

        total_pnl = sum((t.get("pnl_dollar") or 0) for t in closed)
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        avg_winner = (sum(t["pnl_dollar"] for t in wins) / len(wins)) if wins else 0
        avg_loser = (sum(t["pnl_dollar"] for t in losses) / len(losses)) if losses else 0
        avg_hold = (sum((t.get("hold_minutes") or 0) for t in closed) / len(closed)) if closed else 0

        return {
            "period_days": days,
            "brain_runs": brain_count,
            "gate_blocks": block_count,
            "errors": err_count,
            "trades_closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_dollar": round(total_pnl, 2),
            "avg_winner_dollar": round(avg_winner, 2),
            "avg_loser_dollar": round(avg_loser, 2),
            "avg_hold_minutes": round(avg_hold, 0),
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # JSON kolonlarını parse et
        for json_col in ("market_snapshot", "decisions_json", "metadata_json"):
            if d.get(json_col):
                try:
                    d[json_col] = json.loads(d[json_col])
                except Exception:
                    pass
        return d
