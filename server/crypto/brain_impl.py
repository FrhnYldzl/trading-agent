"""
crypto/brain_impl.py — CryptoBrain(BaseBrain) implementation.

Equity'deki claude_brain.py'nin kripto karşılığı. Aynı multi-step reasoning
yapısı, ama kripto piyasasının özelliklerine kalibre edilmiş prompt:

  - 24/7 piyasa (market_open her zaman True, urgency assessment farklı)
  - PDT kuralı yok
  - Volatilite 2-3x equity (risk tabanı 1%, equity 2%)
  - Stop default %4 (equity %2)
  - BTC dominance + alt-coin korelasyonu kritik
  - Asset group concentration (L1/L2/DeFi/Meme/RWA/Infra)
  - Notional emir (USD bazlı), fractional qty
  - Stablecoin'ler hariç (USDC/USDT/USDG)
  - Sektör rotasyonu yerine: BTC-led / ETH-led / alt-season / meme-rally

Returns identical dict structure to equity (BaseBrain compatible).

Equity'de claude_brain.py değiştirilmedi.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import dotenv_values, load_dotenv

from core.asset_class import AssetClass
from core.base_brain import BaseBrain

# Repo root .env'i yükle
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
    _env_vals = dotenv_values(_env_path)
else:
    _env_vals = {}


def _get(key: str) -> str:
    return os.getenv(key) or _env_vals.get(key, "")


# Equity ile aynı model (config'te tanımlı)
try:
    from config import AI_MODEL
    DEFAULT_MODEL = AI_MODEL
except Exception:
    DEFAULT_MODEL = "claude-opus-4-5-20250929"


# ─────────────────────────────────────────────────────────────────
# CryptoBrain class
# ─────────────────────────────────────────────────────────────────

class CryptoBrain(BaseBrain):
    """
    BaseBrain implementation — Claude AI for crypto trading decisions.

    Equity'nin claude_brain.py'sinden farklılıklar:
      - Crypto-spesifik prompt (24/7, BTC dominance, asset groups)
      - Risk rules: max 1% per trade (equity 2%)
      - No PDT references
      - Notional/fractional sizing
      - Asset group concentration limits
    """

    def __init__(self, model: str = None):
        self.model = model or DEFAULT_MODEL
        api_key = _get("ANTHROPIC_API_KEY")
        self.enabled = bool(api_key)
        if self.enabled:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = None

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    # ───────────────────────────────────────────────────────────
    # Public API (BaseBrain)
    # ───────────────────────────────────────────────────────────

    def run_brain(
        self,
        market_data: dict,
        portfolio: dict,
        recent_trades: list = None,
        regime: dict = None,
        sentiment: dict = None,
        learning_context: str = None,
    ) -> dict:
        """
        Tek tarama döngüsü için crypto AI kararı üret.

        Returns equity-compatible dict:
            {
              "decisions": [{
                "ticker": "BTC/USD",
                "action": "long|close_long|hold|watch|reduce",
                "confidence": 1-10,
                "strategy": "momentum|breakout|mean_reversion|defensive",
                "reasoning": "...",
                "entry_zone": "...",
                "stop_loss": "...",
                "take_profit": "...",
                "risk_reward": "...",
                "position_size_pct": float,
                "urgency": "high|medium|low",
                "risk_note": "...",
              }],
              "regime": "...",
              "regime_reasoning": "...",
              "active_strategy": "...",
              "market_summary": "...",
              "portfolio_note": "...",
              "watchlist_alerts": [...],
              "asset_group_view": "...",  # crypto'ya özgü
              "btc_dominance_note": "...",  # crypto'ya özgü
              "timestamp": "...",
              "model": "...",
              "asset_class": "crypto",
            }
        """
        if not self.enabled:
            return self._empty("ANTHROPIC_API_KEY eksik")

        if not market_data or "error" in market_data:
            err = market_data.get("error") if market_data else "veri yok"
            return self._empty(f"Piyasa verisi alınamadı: {err}")

        # Veri formatlama
        cash = portfolio.get("cash", 0)
        equity = portfolio.get("equity", 0)
        positions_text = self._format_positions(portfolio)
        market_text = self._format_market_data(market_data)
        ranking_text = self._format_momentum_ranking(market_data)
        trades_text = self._format_recent_trades(recent_trades or [])

        # Regime context (varsa)
        regime_str = "unknown"
        regime_reasoning = ""
        if regime:
            regime_str = regime.get("regime", "unknown")
            regime_reasoning = regime.get("reasoning", "")

        # Sentiment context (V5.10-β'da news_impl gelince dolacak)
        sentiment_text = ""
        if sentiment:
            sentiment_text = self._format_sentiment(sentiment)

        # Prompt build
        prompt = self._build_master_prompt(
            cash=cash,
            equity=equity,
            positions_text=positions_text,
            market_text=market_text,
            ranking_text=ranking_text,
            trades_text=trades_text,
            detected_regime=regime_str,
            regime_reasoning=regime_reasoning,
            sentiment_text=sentiment_text,
            learning_context=learning_context or "",
        )

        # Claude API
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = msg.content[0].text
            decisions = self._extract_json(response_text)

            decisions["timestamp"] = datetime.now(timezone.utc).isoformat()
            decisions["model"] = self.model
            decisions["asset_class"] = "crypto"
            return decisions

        except Exception as e:
            return self._empty(f"Claude API hatası: {e}")

    def review_past_trades(self, recent_trades: list, portfolio: dict) -> dict:
        """
        Son crypto trade'lerini analiz et, ders çıkar.
        Equity'deki review_past_trades ile aynı şema.
        """
        if not self.enabled or not recent_trades:
            return {"review": "Analiz için yeterli veri yok", "lessons": []}

        trades_text = self._format_recent_trades(recent_trades)
        prompt = f"""You are reviewing your own past CRYPTO trading decisions as a self-improving AI trader.

## RECENT CRYPTO TRADES
{trades_text}

## YOUR JOB
Analyze the pattern of decisions and extract specific, actionable lessons.

Focus on crypto-specific factors:
- Did you respect the higher volatility (2-3x equity)?
- Did you over-concentrate in one asset group (L1, Meme, etc.)?
- Did 24/7 markets cause you to over-trade?
- Did news/sentiment moves catch you off-guard?
- Were stops too tight for crypto's ATR?

## RESPONSE FORMAT (JSON only, no markdown)
{{
  "review": "1-2 sentence overall assessment",
  "lessons": [
    "Specific, actionable lesson 1",
    "Specific, actionable lesson 2"
  ],
  "performance": {{
    "win_rate_pct": 0,
    "avg_winner_pct": 0,
    "avg_loser_pct": 0,
    "biggest_mistake": "..."
  }},
  "suggestions": [
    "Concrete process improvement"
  ]
}}"""

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._extract_json(msg.content[0].text)
        except Exception as e:
            return {"review": f"Hata: {e}", "lessons": []}

    # ───────────────────────────────────────────────────────────
    # Prompt building (crypto-specific)
    # ───────────────────────────────────────────────────────────

    def _build_master_prompt(
        self, cash, equity, positions_text, market_text, ranking_text,
        trades_text, detected_regime, regime_reasoning,
        sentiment_text="", learning_context="",
    ) -> str:
        learning_section = (
            f"\n## LESSONS FROM PAST TRADES\n{learning_context}\n"
            if learning_context else ""
        )
        regime_block = (
            f"\nQuant Regime Reasoning: {regime_reasoning}\n"
            if regime_reasoning else ""
        )
        sentiment_block = (
            f"\n## CRYPTO NEWS & SENTIMENT\n{sentiment_text}\n"
            if sentiment_text else ""
        )

        return f"""You are the Chief Trading Officer of an autonomous AI crypto fund managing a USD-denominated paper portfolio.
You are NOT an indicator interpreter. You are an executive decision-maker for the crypto market.

Your job is to:
1. FIRST identify the crypto regime (BTC-led bull / alt-season / meme-rally / chop / risk-off)
2. SELECT the optimal strategy for the current regime
3. ANALYZE each coin with multi-step reasoning (technicals + flow + group rotation)
4. PROVIDE specific, actionable decisions with entry/exit levels and notional sizing
5. EXPLAIN your reasoning like a fund manager justifying trades

## CURRENT STATE
Market Status: 24/7 OPEN (crypto never closes)
Pre-detected Regime Signal: {detected_regime}{regime_block}
Portfolio Cash: ${cash:,.2f}
Total Equity: ${equity:,.2f}
Asset Class: CRYPTO (USD-paired spot only, no perpetuals, no margin)

## OPEN POSITIONS
{positions_text}

## MARKET DATA (with technical indicators — Core 10)
{market_text}

## MOMENTUM RANKING
{ranking_text}

## RECENT TRADE HISTORY
{trades_text}{learning_section}{sentiment_block}

## CRYPTO-SPECIFIC CONTEXT (READ CAREFULLY)
- Volatility is 2-3x equity. Default ATR%: BTC ~3%, alts often 4-6%.
- BTC is the benchmark — alt-coins follow BTC dominance shifts.
- 24/7 markets = no overnight gap, but flash dumps possible at any hour.
- No PDT rule, fractional positions, instant settlement.
- Asset groups (concentration limits apply):
  L1: BTC, ETH, SOL, ADA, AVAX, DOT, XTZ, FIL
  L2: ARB, POL
  Payment: XRP, LTC, BCH
  DeFi: UNI, AAVE, CRV, SUSHI, YFI, LDO, SKY
  Infra: LINK, GRT, RENDER
  Meme: DOGE, SHIB, PEPE, BONK, WIF, TRUMP, HYPE
  RWA: PAXG, ONDO
  Utility: BAT
- Stablecoins (USDC, USDT, USDG) are EXCLUDED from trading universe.

## STRATEGY FRAMEWORK

### Regime → Strategy mapping:
- **BULL_STRONG / BULL** (BTC uptrend, breadth >70%):
  - MOMENTUM continuation: ride trending leaders
  - Add to winners on BTC pullbacks (dollar-cost-into-strength)
  - Target: alts with breakout volume + relative strength vs BTC
  - Avoid: tops with RSI>75 + extreme funding

- **NEUTRAL** (mixed signals, BTC chopping):
  - SELECTIVE: only highest momentum_score (>70) with confluence
  - Smaller positions (50% of normal size)
  - Prefer BTC/ETH over alts (lower beta)
  - Wait for clear breakout before adding

- **BEAR / BEAR_STRONG** (BTC downtrend, breadth <40%):
  - DEFENSIVE: close longs aggressively, raise cash
  - Mean-reversion bounces ONLY at deep oversold (RSI<25 + BB lower)
  - Stay 70%+ cash, no Meme group exposure
  - Watch for capitulation volume spikes

### Multi-Step Reasoning (REQUIRED for every decision):
For each coin:
1. TREND structure: EMA9 > EMA21 > EMA50 = strong; mixed = caution
2. MOMENTUM: RSI 50-65 ideal; >75 overheating; <30 oversold
3. RELATIVE strength vs BTC: outperforming or lagging?
4. ASSET GROUP context: is the whole group moving together (rotation signal)?
5. RISK level: ATR-based stop, last swing low, key support
6. CATALYST: any narrative or news driving this?
7. CONFLUENCE: how many bullish signals align?
8. R/R ratio: minimum 1:2, prefer 1:3 on alts (higher TP for higher vol)

### Position sizing (USD notional):
Crypto max risk per trade = **1% of equity** (equity uses 2%, crypto half because of volatility)
- Confidence 8-10: up to 1.0% portfolio risk
- Confidence 6-7:  up to 0.7% portfolio risk
- Confidence 4-5:  up to 0.5% portfolio risk
- Confidence 1-3:  NO TRADE — watch only

Recommended notional cap per trade (paper learning phase): $500.
Position_size_pct field = % of total equity allocated to this position.

## RISK RULES (ABSOLUTE)
1. NEVER risk more than 1% of equity per trade
2. NEVER concentrate >40% in a single asset group (L1, Meme, etc.)
3. ALWAYS have a stop-loss plan — crypto's tail risk is real
4. If BTC -10% in 24h: emergency mode, close all longs, no new entries
5. Stablecoin pairs are NOT trading targets
6. NEVER chase a coin already up 15%+ on the day without pullback
7. Default stop: 4% (or 2× ATR, whichever is wider)

## RESPONSE FORMAT
Respond with ONLY this JSON. No markdown, no explanation outside JSON:
{{
  "regime": "bull_strong | bull | neutral | bear | bear_strong",
  "regime_reasoning": "2-3 sentences on current crypto regime (BTC trend, breadth, group rotation)",
  "active_strategy": "momentum | selective_swing | defensive | mean_reversion",
  "btc_dominance_note": "1 sentence: is BTC leading? alts catching up? meme rotation?",
  "asset_group_view": "Brief: which groups are strongest/weakest right now",
  "decisions": [
    {{
      "ticker": "BTC/USD",
      "action": "long | close_long | hold | watch | reduce",
      "confidence": 8,
      "strategy": "momentum",
      "asset_group": "L1",
      "reasoning": "Multi-step: (1) EMA9>21>50 strong uptrend, (2) RSI 64 healthy zone, (3) leading alt rotation, (4) BTC dominance rising. Entry on 4H pullback to EMA9.",
      "entry_zone": "77800-78500",
      "stop_loss": "75200",
      "take_profit": "82000",
      "risk_reward": "1:2.4",
      "position_size_pct": 1.0,
      "urgency": "medium",
      "risk_note": "Watch CPI release tomorrow"
    }}
  ],
  "market_summary": "3-4 sentence overall crypto market analysis with regime context",
  "portfolio_note": "2-3 sentences: portfolio health, asset group concentration, cash level",
  "watchlist_alerts": [
    {{"ticker": "ETH/USD", "alert": "Approaching $2400 resistance — break with volume = next leg"}}
  ]
}}

IMPORTANT:
- Cover top 6-8 coins (don't waste tokens on neutral holds)
- 'short' is NOT supported for spot crypto — only long, close_long, hold, watch, reduce
- Confidence is 1-10 integer
- Reasoning: 1-2 sentences, factor-driven
- Price levels in actual USD (BTC: full price, alts: with appropriate decimals)
- KEEP JSON COMPACT"""

    # ───────────────────────────────────────────────────────────
    # Formatting helpers (crypto-specific)
    # ───────────────────────────────────────────────────────────

    def _format_positions(self, portfolio: dict) -> str:
        positions = portfolio.get("positions", [])
        if not positions:
            return "  No open crypto positions (100% cash)"
        lines = []
        for p in positions:
            pl = p.get("unrealized_pl", 0)
            sign = "+" if pl >= 0 else ""
            lines.append(
                f"  {p.get('symbol', '?')}: {p.get('qty', 0)} @ "
                f"${p.get('avg_entry_price', 0):.4f} | "
                f"Now ${p.get('current_price', 0):.4f} | "
                f"PL {sign}${pl:.2f} ({p.get('asset_group', '?')})"
            )
        return "\n".join(lines)

    def _format_market_data(self, market_data: dict) -> str:
        lines = []
        for ticker, d in market_data.items():
            if ticker.startswith("_") or "error" in d:
                continue
            price = d.get("price", 0)
            change = d.get("change_pct", 0)
            rsi = d.get("rsi14", "?")
            atr = d.get("atr_pct", "?")
            trend = d.get("trend", "?")
            vol_r = d.get("volume_ratio", "?")
            mom = d.get("momentum_score", "?")
            ema9 = d.get("ema9")
            ema21 = d.get("ema21")
            ema50 = d.get("ema50")
            ema_struct = ""
            if ema9 and ema21 and ema50:
                if ema9 > ema21 > ema50:
                    ema_struct = "EMA: bull"
                elif ema9 < ema21 < ema50:
                    ema_struct = "EMA: bear"
                else:
                    ema_struct = "EMA: mixed"
            lines.append(
                f"  {ticker}: ${price} ({change:+.2f}%) | "
                f"RSI {rsi} | ATR%{atr} | Vol×{vol_r} | "
                f"Mom {mom} | {trend} | {ema_struct}"
            )
        return "\n".join(lines) if lines else "  No data"

    def _format_momentum_ranking(self, market_data: dict) -> str:
        items = []
        for ticker, d in market_data.items():
            if ticker.startswith("_") or "error" in d:
                continue
            score = d.get("momentum_score", 0) or 0
            items.append((ticker, score, d.get("change_pct", 0)))
        items.sort(key=lambda x: x[1], reverse=True)
        top = items[:8]
        return "\n".join(
            f"  #{i+1} {t}: momentum {s} (change {c:+.2f}%)"
            for i, (t, s, c) in enumerate(top)
        ) or "  No ranking data"

    def _format_recent_trades(self, trades: list) -> str:
        if not trades:
            return "  No recent trades"
        lines = []
        for t in trades[-10:]:
            lines.append(
                f"  {t.get('timestamp', '?')[:16]} {t.get('action', '?')} "
                f"{t.get('symbol', '?')} qty={t.get('qty', '?')} "
                f"@ ${t.get('price', 0):.4f} → {t.get('result', '?')}"
            )
        return "\n".join(lines)

    def _format_sentiment(self, sentiment: dict) -> str:
        # V5.10-β'da crypto/news.py geldiğinde gerçek sentiment formatı
        lines = []
        for ticker, info in sentiment.items():
            if isinstance(info, dict):
                score = info.get("score", "?")
                summary = info.get("summary", "")
                lines.append(f"  {ticker}: sentiment {score} — {summary}")
        return "\n".join(lines) if lines else "  No sentiment data"

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Markdown fence'leri vs. ile gelse de JSON'u çek."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except Exception:
            # Fallback: ilk { ile son } arası
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end+1])
                except Exception:
                    pass
            return {"error": "JSON parse failed", "raw": text[:500]}

    @staticmethod
    def _empty(reason: str) -> dict:
        return {
            "decisions": [],
            "regime": "unknown",
            "regime_reasoning": reason,
            "active_strategy": "none",
            "market_summary": reason,
            "portfolio_note": "",
            "watchlist_alerts": [],
            "btc_dominance_note": "",
            "asset_group_view": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_class": "crypto",
            "error": reason,
        }
