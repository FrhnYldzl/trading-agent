"""
claude_brain.py — Otonom AI Trading Agent Beyni (V2)

Bu modül bir "emir iletici" degil, bir "Bas Trader"dir.
Claude'u bir indikatör yorumlayicisi olarak degil,
Hedge Fund Müdürü pozisyonunda konumlandirır.

Karar döngüsü:
  1. Piyasa rejimini belirle (boga/ayi/yatay)
  2. Rejime uygun stratejiyi sec (momentum/mean-reversion/defensive)
  3. Her hisse icin multi-step analiz yap
  4. Risk/ödül oranına göre güven skoru ver
  5. Aksiyonable kararları gerekceleriyle birlikte döndür

Ross Cameron + Adaptif Rejim = Gerçek AI Agent
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import dotenv_values, load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)
_env_vals = dotenv_values(_env_path)

def _get(key): return os.getenv(key) or _env_vals.get(key, "")

client = anthropic.Anthropic(api_key=_get("ANTHROPIC_API_KEY"))
from config import AI_MODEL
MODEL = AI_MODEL

# ─────────────────────────────────────────────────────────────────
# Ana Karar Motoru
# ─────────────────────────────────────────────────────────────────

def run_brain(
    market_data: dict,
    portfolio: dict,
    recent_trades: list,
    auto_execute: bool = False,
) -> dict:
    """
    Claude Otonom Karar Motoru — V2

    Sadece "al/sat" demez:
    1. Piyasa rejimini analiz eder
    2. Rejime uygun stratejiyi secer
    3. Her hisse icin multi-step reasoning yapar
    4. Risk/ödül + güven skoru hesaplar
    5. "Neden bu islemi yapmaliyiz?" sorusunu cevaplar

    Returns:
        {
          "decisions": [{
            "ticker": "NVDA",
            "action": "long",
            "confidence": 8,          # 1-10 skala
            "strategy": "momentum",   # hangi strateji
            "reasoning": "...",       # multi-step gerekce
            "entry_zone": "950-960",
            "stop_loss": "935",
            "take_profit": "985",
            "risk_reward": "1:2.5",
            "position_size_pct": 1.5, # portfolyonun %'si
            "urgency": "high",        # high/medium/low
            "risk_note": "..."
          }],
          "regime": "bull",
          "regime_reasoning": "...",
          "active_strategy": "momentum",
          "market_summary": "...",
          "portfolio_note": "...",
          "watchlist_alerts": [...],
          "timestamp": "..."
        }
    """
    if not _get("ANTHROPIC_API_KEY"):
        return _empty("API anahtari eksik")

    if "error" in market_data:
        return _empty(f"Piyasa verisi alinamadi: {market_data['error']}")

    # Meta bilgiyi ayir
    meta = market_data.get("_meta", {})
    market_open = meta.get("market_open", False)
    detected_regime = meta.get("regime", "unknown")

    # V3.3: Kantitatif rejim + anomali + sentiment context
    quant_context = ""
    try:
        from regime_detector import detect_regime
        quant = detect_regime(market_data)
        quant_context += f"\n## QUANTITATIVE REGIME ANALYSIS (V3.3)\n"
        quant_context += f"Quant Regime: {quant['regime']} (score: {quant['quant_score']}/100, confidence: {quant['confidence']}%)\n"
        quant_context += f"Analysis: {quant['reasoning']}\n"
        if quant['regime'] != detected_regime and detected_regime != "unknown":
            quant_context += f"NOTE: Quant regime ({quant['regime']}) differs from technical regime ({detected_regime}) — investigate divergence.\n"
    except Exception:
        pass

    try:
        from anomaly_detector import detect_anomalies
        anomalies = detect_anomalies(market_data)
        if anomalies.get("anomaly_count", 0) > 0:
            quant_context += f"\n## ANOMALY ALERTS (V3.3)\n"
            quant_context += f"Risk Level: {anomalies['risk_level'].upper()} — {anomalies['anomaly_count']} anomalies detected\n"
            for a in anomalies["anomalies"][:5]:
                quant_context += f"  - [{a['severity'].upper()}] {a['ticker']}: {a['detail']}\n"
    except Exception:
        pass

    # Portföy özetini hazirla
    positions_text = _format_positions(portfolio)
    market_text    = _format_market_data(market_data)
    trades_text    = _format_recent_trades(recent_trades)
    ranking_text   = _format_momentum_ranking(market_data)

    # Gecmis derslerden ogrenme context'i
    try:
        from trade_journal import get_learning_context
        learning_context = get_learning_context(limit=5)
    except Exception:
        learning_context = ""

    pdt_left = portfolio.get("pdt_trades_left", 3)
    cash     = portfolio.get("cash", 0)
    equity   = portfolio.get("equity", 0)

    prompt = _build_master_prompt(
        cash=cash,
        equity=equity,
        pdt_left=pdt_left,
        positions_text=positions_text,
        market_text=market_text,
        trades_text=trades_text,
        ranking_text=ranking_text,
        detected_regime=detected_regime,
        market_open=market_open,
        auto_execute=auto_execute,
        learning_context=learning_context,
        quant_context=quant_context,
    )

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        result = _extract_json(text)

        # Metadata ekle
        result["timestamp"]    = datetime.now(timezone.utc).isoformat()
        result["auto_execute"] = auto_execute
        result["market_open"]  = market_open
        result["market_data_snapshot"] = {
            k: {
                "price": v.get("price"),
                "signal": v.get("signal"),
                "momentum_score": v.get("momentum_score"),
                "rsi14": v.get("rsi14"),
                "volume_ratio": v.get("volume_ratio"),
                "trend": v.get("trend"),
                "macd": v.get("macd"),
                "macd_histogram": v.get("macd_histogram"),
                "macd_cross": v.get("macd_cross"),
                "bb_position": v.get("bb_position"),
                "bb_width": v.get("bb_width"),
            }
            for k, v in market_data.items()
            if isinstance(v, dict) and not k.startswith("_")
        }
        return result

    except Exception as e:
        return _empty(f"Claude hatasi: {str(e)[:200]}")


# ─────────────────────────────────────────────────────────────────
# Master Prompt — Claude'u "Bas Trader" Olarak Konumlandirir
# ─────────────────────────────────────────────────────────────────

def _build_master_prompt(
    cash, equity, pdt_left, positions_text, market_text,
    trades_text, ranking_text, detected_regime, market_open, auto_execute,
    learning_context="", quant_context=""
) -> str:
    market_status = "OPEN" if market_open else "CLOSED (pre/post analysis mode)"

    # Learning context (gecmis derslerden ogrenme)
    learning_section = learning_context if learning_context else ""

    return f"""You are the Chief Trading Officer of an autonomous AI hedge fund managing a US stock portfolio.
You are NOT an indicator interpreter. You are an executive decision-maker.

Your job is to:
1. FIRST determine the market regime (bull/bear/neutral) — this drives everything
2. SELECT the optimal strategy for the current regime
3. ANALYZE each stock with multi-step reasoning (not just indicators)
4. PROVIDE specific, actionable decisions with entry/exit levels and position sizing
5. EXPLAIN your reasoning like a fund manager justifying trades to investors

## CURRENT STATE
Market Status: {market_status}
Pre-detected Regime Signal: {detected_regime}
Portfolio Cash: ${cash:,.2f}
Total Equity: ${equity:,.2f}
PDT Day Trades Remaining: {pdt_left}/3

## OPEN POSITIONS
{positions_text}

## MARKET DATA (with technical indicators)
{market_text}

## MOMENTUM RANKING (sorted by momentum score)
{ranking_text}

## RECENT TRADE HISTORY
{trades_text}
{learning_section}
{quant_context}

## STRATEGY FRAMEWORK

### Strategy Selection (based on regime):
- **BULL market**: Use MOMENTUM strategy (Ross Cameron Gap & Go)
  - Target: stocks with gap_pct > 2%, volume_ratio > 1.5x, strong_uptrend
  - Entry: on pullback to VWAP or EMA9 support
  - Exit: trail stop at EMA9, take profit at 2:1 R/R minimum

- **NEUTRAL market**: Use SELECTIVE SWING strategy
  - Target: only highest momentum_score stocks (>70)
  - Entry: only at key support levels with volume confirmation
  - Smaller position sizes (reduce risk 50%)
  - Prefer ETFs (SPY, QQQ) over individual stocks

- **BEAR market**: Use DEFENSIVE / MEAN REVERSION strategy
  - Close or reduce existing long positions
  - Short only highest-conviction setups
  - Hold more cash (>60% portfolio)
  - Consider inverse plays only with extreme confidence

### Ross Cameron Momentum Criteria (for bull regime):
1. Pre-market gap > 4% with catalyst
2. Relative volume > 2x average
3. Float rotation (high volume relative to shares outstanding)
4. First pullback to VWAP = ideal entry
5. NEVER chase — if missed entry, wait for next setup

### Multi-Step Reasoning (REQUIRED for every decision):
For each ticker, answer these questions internally:
1. What is the TREND? (EMA structure: 9>21>50 = strong uptrend)
2. What is the MOMENTUM? (RSI band, volume confirmation, MACD histogram direction)
3. What does MACD say? (bullish_cross = buy signal, bearish_cross = sell signal, histogram growing = momentum increasing)
4. What do BOLLINGER BANDS say? (BB_Pos<0.2 = oversold bounce opportunity, BB_Pos>0.8 = overbought risk, BB_Width high = breakout potential)
5. Where is the RISK? (ATR-based stop, key support/resistance, Bollinger lower band as support)
6. What is the CATALYST? (why is this moving?)
7. Does this ALIGN with the regime? (don't go long in a bear market)
8. What is the R/R ratio? (minimum 1:2, prefer 1:3)

### SIGNAL CONFLUENCE (V3):
Strong setups require MULTIPLE confirmations:
- MACD bullish cross + RSI in 40-65 zone + uptrend = HIGH confidence
- MACD bearish cross + RSI > 70 + downtrend = SELL signal
- Bollinger squeeze (low BB_Width) then expansion = breakout imminent
- Price at lower BB + bullish MACD = mean reversion buy
- Price at upper BB + bearish MACD divergence = potential reversal

## RISK RULES (ABSOLUTE — NEVER VIOLATE)
1. NEVER risk more than 2% of total equity per trade
2. Max 3 day trades per 5-day rolling window (PDT rule)
3. If PDT trades left = 0, ONLY swing trades (hold overnight)
4. NEVER go all-in on a single position
5. If regime = bear, max 40% invested, 60% cash minimum
6. ALWAYS have a stop-loss plan before entry
7. If market is CLOSED: analyze and prepare watchlist, do NOT recommend immediate execution

## POSITION SIZING RULES
- Confidence 8-10: up to 2.0% portfolio risk
- Confidence 6-7: up to 1.5% portfolio risk
- Confidence 4-5: up to 1.0% portfolio risk
- Confidence 1-3: NO TRADE — watch only

## RESPONSE FORMAT
Respond with ONLY this JSON structure. No other text, no markdown, no explanation outside JSON:
{{
  "regime": "bull | bear | neutral",
  "regime_reasoning": "2-3 sentences explaining WHY this is the current regime based on data",
  "active_strategy": "momentum | selective_swing | defensive | mean_reversion",
  "decisions": [
    {{
      "ticker": "NVDA",
      "action": "long | short | close_long | close_short | hold | watch | reduce",
      "confidence": 8,
      "strategy": "momentum",
      "reasoning": "Multi-step: (1) Strong uptrend EMA9>21>50, (2) RSI 58 ideal zone, (3) Vol ratio 2.1x confirms institutional buying, (4) AI chip demand catalyst, (5) Aligns with bull regime. Entry at VWAP pullback.",
      "entry_zone": "950-960",
      "stop_loss": "935",
      "take_profit": "985",
      "risk_reward": "1:2.5",
      "position_size_pct": 1.5,
      "urgency": "high | medium | low",
      "risk_note": "Earnings in 2 weeks — consider reducing before"
    }}
  ],
  "market_summary": "3-4 sentence overall market analysis with regime context",
  "portfolio_note": "2-3 sentences: current portfolio health, suggested adjustments, cash allocation advice",
  "watchlist_alerts": [
    {{"ticker": "COIN", "alert": "Approaching breakout at $250 resistance, watch for volume spike"}}
  ]
}}

IMPORTANT RULES FOR RESPONSE:
- Include TOP 8-10 most relevant tickers (skip low-interest holds to save space)
- Confidence is 1-10 integer
- Reasoning should be 1-2 sentences with key factors
- entry_zone, stop_loss, take_profit: specific price levels
- If market is CLOSED: urgency="low", note next-session plan
- KEEP JSON COMPACT — no extra whitespace or verbose explanations"""


# ─────────────────────────────────────────────────────────────────
# Formatlama Yardimcilari
# ─────────────────────────────────────────────────────────────────

def _format_positions(portfolio: dict) -> str:
    positions = portfolio.get("positions", [])
    if not positions:
        return "  No open positions (100% cash)"
    lines = []
    for p in positions:
        pl = p.get("unrealized_pl", 0)
        pl_sign = "+" if pl >= 0 else ""
        lines.append(
            f"  {p['ticker']}: {p['qty']} shares @ ${p['avg_entry']:.2f} "
            f"| Now ${p['current_price']:.2f} | PL {pl_sign}${pl:.2f}"
        )
    return "\n".join(lines)


def _format_market_data(market_data: dict) -> str:
    lines = []
    for ticker, d in market_data.items():
        if not isinstance(d, dict) or ticker.startswith("_"):
            continue
        if "price" not in d:
            continue
        macd_info = f"MACD={d.get('macd',0)} Hist={d.get('macd_histogram',0)} {d.get('macd_cross','')}"
        bb_info = f"BB_Pos={d.get('bb_position','?')} BB_W={d.get('bb_width','?')}"
        lines.append(
            f"  {ticker}: ${d['price']} ({d['change_pct']:+.1f}%) "
            f"Gap:{d.get('gap_pct',0):+.1f}% "
            f"| EMA9={d['ema9']} EMA21={d['ema21']} EMA50={d.get('ema50','?')} "
            f"| RSI={d['rsi14']} ATR%={d.get('atr_pct','?')} "
            f"| Vol={d.get('volume_ratio',0):.1f}x "
            f"| VWAP=${d.get('vwap','?')} "
            f"| {macd_info} | {bb_info} "
            f"| Trend: {d.get('trend','?')} Signal: {d['signal']} "
            f"| MomentumScore: {d.get('momentum_score',50)}"
        )
    return "\n".join(lines) or "  No market data available"


def _format_recent_trades(recent_trades: list) -> str:
    if not recent_trades:
        return "  No recent trades"
    lines = []
    for t in recent_trades[:10]:
        lines.append(
            f"  {t.get('timestamp','')[:16]} | {t.get('ticker')} "
            f"{t.get('action')} @ ${t.get('price','?')} -> {t.get('status')}"
        )
    return "\n".join(lines)


def _format_momentum_ranking(market_data: dict) -> str:
    """Momentum skoruna göre sirali liste (en yüksekten en düsüge)."""
    stocks = []
    for ticker, d in market_data.items():
        if not isinstance(d, dict) or ticker.startswith("_"):
            continue
        if "momentum_score" in d:
            stocks.append((ticker, d["momentum_score"], d.get("signal", "?"), d.get("change_pct", 0)))

    stocks.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (ticker, score, signal, change) in enumerate(stocks, 1):
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        lines.append(f"  #{i} {ticker}: {score}/100 [{bar}] Signal={signal} ({change:+.1f}%)")
    return "\n".join(lines) or "  No ranking data"


# ─────────────────────────────────────────────────────────────────
# JSON Cikartma
# ─────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Claude ciktisından JSON blogu cikarir — hata toleransli."""
    import re

    # Markdown code block temizligi (```json ... ```)
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()

    # Ilk { ile son } arasini al
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Trailing comma temizligi (Claude bazen yapar)
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise


# ─────────────────────────────────────────────────────────────────
# Post-Trade Review (V2 — Ögrenme Döngüsü)
# ─────────────────────────────────────────────────────────────────

def review_past_trades(recent_trades: list, portfolio: dict) -> dict:
    """
    Son islemleri analiz eder ve ögrenme cikarimları üretir.
    Her islem kapandiktan sonra: "Neden kazandim/kaybettim?" analizi.
    """
    if not _get("ANTHROPIC_API_KEY") or not recent_trades:
        return {"review": "Analiz icin yeterli veri yok", "lessons": []}

    trades_text = _format_recent_trades(recent_trades)

    prompt = f"""You are reviewing your own past trading decisions as a self-improving AI trader.

## RECENT TRADES
{trades_text}

## CURRENT PORTFOLIO
Cash: ${portfolio.get('cash', 0):,.2f}
Equity: ${portfolio.get('equity', 0):,.2f}

## YOUR TASK
Analyze each trade and provide:
1. What went RIGHT (repeat these patterns)
2. What went WRONG (avoid these patterns)
3. Specific lessons for future trades
4. Win rate estimate and risk-adjusted performance

Respond with JSON only:
{{
  "overall_grade": "A/B/C/D/F",
  "win_rate_estimate": "60%",
  "lessons": [
    {{"type": "positive", "lesson": "..."}},
    {{"type": "negative", "lesson": "..."}}
  ],
  "strategy_adjustments": ["..."],
  "risk_assessment": "Are we taking too much or too little risk?"
}}"""

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()
        return _extract_json(text)
    except Exception as e:
        return {"review": f"Review hatasi: {str(e)[:100]}", "lessons": []}


# ─────────────────────────────────────────────────────────────────
# Yardimcilar
# ─────────────────────────────────────────────────────────────────

def _empty(reason: str) -> dict:
    return {
        "decisions": [],
        "regime": "unknown",
        "regime_reasoning": reason,
        "active_strategy": "none",
        "market_summary": reason,
        "portfolio_note": "",
        "watchlist_alerts": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "auto_execute": False,
        "error": reason,
    }


def pdt_trades_left(recent_trades: list) -> int:
    """Son 5 is gününde yapilan day trade sayisina göre kalan limiti hesapla."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    day_trades = sum(
        1 for t in recent_trades
        if t.get("timestamp") and t.get("timestamp") > cutoff.isoformat()
        and t.get("action") in ("long", "short")
    )
    return max(0, 3 - day_trades)
