"""
crypto/audit_impl.py — V5.10-δ: Gemini Auditor (crypto-specific)

Equity'nin gemini_auditor.py ile aynı felsefe: Claude (brain) karar verir,
Gemini bağımsız ikinci görüş verir. İki AI uyuşursa karar güçlü.

Crypto için kalibre:
  - 24/7 market context (overnight gap yok ama flash dump var)
  - Asset group concentration (L1/DeFi/Meme/etc)
  - BTC dominance + alt-rotation farkındalığı
  - Volatilite 2-3x equity → daha tutucu olmalı
  - Stablecoin'ler hariç (zaten brain göndermez)
  - PDT yok

Audit verdict'leri:
  APPROVE  — Karar mantıklı, devam et
  REJECT   — Karar riskli, işlem yapma
  MODIFY   — Karar fikren OK ama parametreler değişsin (stop tighter, size smaller)

Aşağıdaki risk_flags Gemini'nin spotlamasını teşvik ediyor:
  - regime_mismatch: bull'da uzun, bear'da uzun yapma
  - overheating: RSI > 75 + uzun = kapan/al değil
  - volatility_extreme: ATR > 8% (kripto için bile)
  - concentration: aynı asset group'ta zaten ağırsa
  - flash_dump_proximity: BTC son 4hr'da %5+ düştüyse
  - volume_anomaly: vol×6+ — investigate
  - news_catalyst_pending: bilinen büyük olay (CPI, FOMC, vs)

API key resolution:
  1. CRYPTO_GEMINI_API_KEY (dedicated)
  2. GEMINI_API_KEY (default)
  3. SCAN: 'AIza' prefix'i (Google API key formatı) ile başlayan herhangi
     bir env var (ör. GEMINI_MERIDIAN_CRYPTO_TERMINAL)
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from core.asset_class import AssetClass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────
# CryptoAuditor
# ─────────────────────────────────────────────────────────────────

class CryptoAuditor:
    """
    Gemini-based crypto trading decision auditor.

    Asset-agnostic değil — kripto-spesifik prompt.
    Equity'nin gemini_auditor.py'sından AYRI (asset_class izolasyonu).
    """

    asset_class = AssetClass.CRYPTO
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self, model: str = None):
        self.model = model or self.DEFAULT_MODEL
        api_key, source = self._resolve_api_key()
        self.api_key_source = source
        self.api_key = api_key
        self.enabled = bool(api_key)
        self._last_audit: dict = {
            "status": "Henüz audit yapılmadı",
            "timestamp": None,
            "results": [],
        }

    @staticmethod
    def _resolve_api_key():
        """
        Gemini key esnek çözüm — kullanıcı Railway'de hangi isimle koyduysa bul.
          1. CRYPTO_GEMINI_API_KEY
          2. GEMINI_API_KEY
          3. SCAN: 'AIza' prefix (Google API key formatı)
        """
        from dotenv import dotenv_values
        from pathlib import Path
        env_path = Path(__file__).parent.parent.parent / ".env"
        env_vals = dotenv_values(env_path) if env_path.exists() else {}

        for name in ("CRYPTO_GEMINI_API_KEY", "GEMINI_API_KEY"):
            v = os.getenv(name) or env_vals.get(name, "")
            if v:
                return v, f"{name} (env)"

        # Scan all env vars for 'AIza' prefix (Google API key signature)
        all_keys = {**os.environ, **env_vals}
        for k, v in all_keys.items():
            if isinstance(v, str) and v.startswith("AIza"):
                return v, f"{k} (auto-detected, AIza prefix)"

        return None, "MISSING (hiçbir env var AIza ile başlamıyor)"

    def get_last_audit(self) -> dict:
        return self._last_audit

    # ───────────────────────────────────────────────────────
    # MAIN — audit a list of decisions
    # ───────────────────────────────────────────────────────

    def audit_decisions(
        self,
        decisions: list,
        market_data: dict,
        portfolio: dict,
        regime: str = "unknown",
    ) -> list[dict]:
        """
        Her actionable decision için Gemini'den ikinci görüş al.

        Returns: [{ticker, claude_action, audit_verdict, reasoning,
                   risk_flags, risk_score, modified_params}]
        """
        if not self.enabled:
            self._last_audit = {
                "status": f"Gemini disabled: {self.api_key_source}",
                "timestamp": _now_iso(),
                "results": [],
            }
            return []

        # Sadece actionable kararları denetle (hold/watch hariç)
        actionable = [
            d for d in decisions
            if (d.get("action") or "").lower() in ("long", "close_long", "reduce")
        ]
        if not actionable:
            self._last_audit = {
                "status": "Denetlenecek aksiyon yok (hepsi hold/watch)",
                "timestamp": _now_iso(),
                "results": [],
            }
            return []

        market_summary = self._format_market(market_data, actionable)
        portfolio_summary = self._format_portfolio(portfolio)

        results = []
        for decision in actionable:
            try:
                result = self._audit_single(decision, market_summary, portfolio_summary, regime)
                results.append(result)
            except Exception as e:
                # Gemini offline → auto-approve (graceful degradation)
                results.append({
                    "ticker": decision.get("ticker", "?"),
                    "claude_action": decision.get("action", "?"),
                    "claude_confidence": decision.get("confidence", 0),
                    "audit_verdict": "APPROVE",
                    "reasoning": f"Gemini offline — auto-approved. Error: {str(e)[:100]}",
                    "risk_flags": ["gemini_unavailable"],
                    "risk_score": 5,
                    "modified_params": {},
                })

        self._last_audit = {
            "status": "ok",
            "timestamp": _now_iso(),
            "total_decisions": len(actionable),
            "approved": sum(1 for r in results if r["audit_verdict"] == "APPROVE"),
            "rejected": sum(1 for r in results if r["audit_verdict"] == "REJECT"),
            "modified": sum(1 for r in results if r["audit_verdict"] == "MODIFY"),
            "results": results,
        }
        print(
            f"[CryptoAudit] {len(actionable)} karar denetlendi: "
            f"{self._last_audit['approved']} onay / "
            f"{self._last_audit['rejected']} red / "
            f"{self._last_audit['modified']} modify"
        )
        return results

    # ───────────────────────────────────────────────────────
    # Single decision audit
    # ───────────────────────────────────────────────────────

    def _audit_single(
        self, decision: dict, market_summary: str,
        portfolio_summary: str, regime: str,
    ) -> dict:
        from google import genai

        client = genai.Client(api_key=self.api_key)

        ticker = decision.get("ticker", "?")
        action = decision.get("action", "?")
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "")
        entry_zone = decision.get("entry_zone", "?")
        stop_loss = decision.get("stop_loss", "?")
        take_profit = decision.get("take_profit", "?")
        risk_reward = decision.get("risk_reward", "?")
        position_pct = decision.get("position_size_pct", 0)
        asset_group = decision.get("asset_group", "?")

        prompt = f"""You are the RISK AUDITOR of an AI crypto fund. Your job is to independently verify trading decisions made by the primary AI (Claude).

You must be SKEPTICAL and CONSERVATIVE. Your role is to catch mistakes, flag risks, and prevent bad trades.

## CRYPTO MARKET CONTEXT
- 24/7 markets (no overnight gap, but flash dumps happen at any hour)
- Volatility 2-3x equity (BTC ATR ~3%, alts 4-6%)
- BTC is benchmark — alts follow BTC dominance
- Asset groups (concentration risk): L1, L2, Payment, DeFi, Infra, Meme, RWA, Utility
- Spot only (no shorts, no leverage in this fund)

## CURRENT REGIME
{regime}

## PORTFOLIO STATE
{portfolio_summary}

## MARKET DATA
{market_summary}

## CLAUDE'S DECISION TO AUDIT
Ticker: {ticker}  ({asset_group})
Action: {action}
Confidence: {confidence}/10
Entry Zone: {entry_zone}
Stop Loss: {stop_loss}
Take Profit: {take_profit}
Risk/Reward: {risk_reward}
Position Size: {position_pct}% of portfolio
Claude's Reasoning: {reasoning}

## YOUR AUDIT CHECKLIST (crypto-specific)
1. Does action align with regime? (Bear regime → no new longs)
2. Is RSI dangerous? (> 75 = overheating, > 80 = extreme — REJECT new longs)
3. Is the stop-loss appropriate for crypto volatility? (Too tight = whipsawed)
4. Is position size reasonable? (Max 1% risk per trade for crypto)
5. Asset group concentration? (Already heavy in same group?)
6. Any volume anomaly that suggests manipulation? (Vol×6+ without catalyst)
7. Is this a "buying the top" move? (>15% up on day = chase, REJECT)
8. Flash dump risk in last 4h?

## VERDICT OPTIONS
APPROVE — Mantıklı, riskler kabul edilebilir
REJECT  — Riskli, işlem yapılmamalı (sebep ile)
MODIFY  — Karar fikren OK, ama parametreler değişsin (stop, size)

## RESPONSE FORMAT (JSON only, no markdown)
{{
  "verdict": "APPROVE | REJECT | MODIFY",
  "reasoning": "2-3 sentences",
  "risk_flags": ["regime_mismatch", "overheating", "concentration", ...],
  "risk_score": 1-10,
  "modified_params": {{}}
}}

For MODIFY: include changed params in modified_params, e.g.:
{{"stop_loss": "new_value", "position_size_pct": 0.5, "take_profit": "new_value"}}"""

        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            parsed = json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end+1])
            else:
                raise

        return {
            "ticker": ticker,
            "claude_action": action,
            "claude_confidence": confidence,
            "asset_group": asset_group,
            "audit_verdict": parsed.get("verdict", "APPROVE").upper(),
            "reasoning": parsed.get("reasoning", ""),
            "risk_flags": parsed.get("risk_flags", []),
            "risk_score": parsed.get("risk_score", 5),
            "modified_params": parsed.get("modified_params", {}),
        }

    # ───────────────────────────────────────────────────────
    # Format helpers
    # ───────────────────────────────────────────────────────

    @staticmethod
    def _format_market(market_data: dict, decisions: list) -> str:
        lines = []
        tickers = {d.get("ticker") for d in decisions if d.get("ticker")}
        for sym in sorted(tickers):
            d = market_data.get(sym, {})
            if not d or "error" in d:
                continue
            lines.append(
                f"  {sym}: ${d.get('price')} ({d.get('change_pct'):+.2f}%) | "
                f"RSI {d.get('rsi14')} | ATR%{d.get('atr_pct')} | "
                f"Vol×{d.get('volume_ratio')} | trend={d.get('trend')}"
            )
        # Always include BTC for context (crypto benchmark)
        if "BTC/USD" not in tickers:
            btc = market_data.get("BTC/USD", {})
            if btc:
                lines.insert(0,
                    f"  BTC/USD (benchmark): ${btc.get('price')} "
                    f"({btc.get('change_pct'):+.2f}%) | RSI {btc.get('rsi14')} | "
                    f"trend={btc.get('trend')}"
                )
        return "\n".join(lines) or "  No data"

    @staticmethod
    def _format_portfolio(portfolio: dict) -> str:
        cash = portfolio.get("cash", 0)
        equity = portfolio.get("equity", 0)
        positions = portfolio.get("positions", [])
        lines = [f"  Cash: ${cash:,.2f} | Equity: ${equity:,.2f}"]
        if positions:
            lines.append(f"  Open positions ({len(positions)}):")
            for p in positions:
                lines.append(
                    f"    {p.get('symbol')}: {p.get('qty')} @ "
                    f"${p.get('avg_entry_price'):.4f} | "
                    f"PL ${p.get('unrealized_pl', 0):+.2f} ({p.get('asset_group', '?')})"
                )
        else:
            lines.append("  No open positions (100% cash)")
        return "\n".join(lines)
