"""
crypto/regime_impl.py — CryptoRegimeDetector(BaseRegimeDetector).

Equity regime_detector'ünün mantığını koruyan ama kripto için kalibre edilmiş
versiyonu. 4 bileşen yine aynı: volatility / trend / momentum / breadth.

Equity'den farklılıklar:

  Volatilite eşikleri:
    Equity:  ATR%  ≤1.0 = düşük, 1.5-2 = normal, 3 = yüksek, 4+ = ekstrem
    Crypto:  ATR%  ≤2.5 = düşük, 3-4 = normal, 5-7 = yüksek, 8+ = ekstrem
    (BTC günlük ATR'i tipik %3-5, equity'nin 2-3x'i)

  Benchmark:
    Equity:  SPY (genel piyasa proxy'si)
    Crypto:  BTC/USD (kripto piyasası proxy'si — alt-coin'ler BTC'ye
             yüksek korelasyonludur, "BTC dominance" rejim göstergesi)

  MACD:
    Equity'de regime_detector MACD field'larını okur. Crypto data layer'ı
    şu an MACD hesaplamıyor (V5.9-α'da eklendi: EMA/RSI/ATR var, MACD yok).
    Bu yüzden momentum bileşeni MACD'siz hesaplanır — ileride eklenebilir.

  Breadth:
    Equity'de "advancing/declining" tüm watchlist üzerinden.
    Crypto'da Core 10 üzerinden — broad evren çok büyük olduğu için
    breadth ölçümü sadece blue-chip'ler üzerinde temsili.
"""

from datetime import datetime, timezone

from core.asset_class import AssetClass
from core.base_regime import BaseRegimeDetector


BTC_BENCHMARK = "BTC/USD"


# ─────────────────────────────────────────────────────────────────
# Bileşen analizleri — kripto kalibrasyonu
# ─────────────────────────────────────────────────────────────────

def _volatility_regime_crypto(market_data: dict, tickers: list) -> dict:
    """Crypto-kalibre volatilite. Eşikler equity'nin 2-3x'i."""
    atr_pcts = []
    for t in tickers:
        d = market_data.get(t, {})
        price = d.get("price", 0)
        atr = d.get("atr14", 0)
        if price > 0 and atr and atr > 0:
            atr_pcts.append(atr / price * 100)

    if not atr_pcts:
        return {"score": 50, "avg_atr_pct": 0, "label": "unknown"}

    avg_atr = sum(atr_pcts) / len(atr_pcts)

    # Crypto eşikleri (equity'nin 2-3x)
    if avg_atr <= 2.5:
        score = 80; label = "low_volatility"
    elif avg_atr <= 4.0:
        score = 70; label = "normal"
    elif avg_atr <= 6.0:
        score = 50; label = "elevated"
    elif avg_atr <= 8.0:
        score = 35; label = "high"
    else:
        score = 20; label = "extreme"

    return {
        "score": round(score, 1),
        "avg_atr_pct": round(avg_atr, 2),
        "label": label,
    }


def _trend_regime_crypto(market_data: dict, tickers: list) -> dict:
    """BTC-benchmarked trend rejimi."""
    trend_counts = {"uptrend": 0, "sideways": 0, "downtrend": 0, "unknown": 0}
    ema_alignments = []

    for t in tickers:
        d = market_data.get(t, {})
        trend = d.get("trend", "sideways")
        trend_counts[trend] = trend_counts.get(trend, 0) + 1

        ema9 = d.get("ema9", 0) or 0
        ema21 = d.get("ema21", 0) or 0
        ema50 = d.get("ema50", 0) or 0
        price = d.get("price", 0) or 0

        if price > 0 and ema9 > 0 and ema21 > 0 and ema50 > 0:
            if price > ema9 > ema21 > ema50:
                ema_alignments.append(2)
            elif ema9 > ema21:
                ema_alignments.append(1)
            elif ema9 < ema21 < ema50 and price < ema50:
                ema_alignments.append(-2)
            elif ema9 < ema21:
                ema_alignments.append(-1)
            else:
                ema_alignments.append(0)

    total = len(tickers) or 1
    bullish_pct = trend_counts.get("uptrend", 0) / total * 100
    bearish_pct = trend_counts.get("downtrend", 0) / total * 100

    avg_alignment = sum(ema_alignments) / len(ema_alignments) if ema_alignments else 0
    alignment_score = (avg_alignment + 2) / 4 * 100

    # BTC bonus (equity'deki SPY bonus karşılığı)
    btc_data = market_data.get(BTC_BENCHMARK, {})
    btc_trend = btc_data.get("trend", "sideways")
    btc_bonus = {"uptrend": 10, "sideways": 0, "downtrend": -10, "unknown": 0}.get(btc_trend, 0)

    score = alignment_score * 0.6 + bullish_pct * 0.4 + btc_bonus
    score = max(0, min(100, score))

    label = "bullish" if bullish_pct > 60 else "bearish" if bearish_pct > 60 else "mixed"

    return {
        "score": round(score, 1),
        "bullish_pct": round(bullish_pct, 1),
        "bearish_pct": round(bearish_pct, 1),
        "avg_ema_alignment": round(avg_alignment, 2),
        "btc_trend": btc_trend,
        "label": label,
    }


def _momentum_regime_crypto(market_data: dict, tickers: list) -> dict:
    """RSI + momentum_score (MACD'siz, V5.9-α data layer'da MACD yok)."""
    rsis = []
    momentum_scores = []

    for t in tickers:
        d = market_data.get(t, {})
        rsi = d.get("rsi14")
        mom = d.get("momentum_score", 50)
        if rsi is not None:
            rsis.append(rsi)
        momentum_scores.append(mom)

    avg_rsi = sum(rsis) / len(rsis) if rsis else 50
    avg_mom = sum(momentum_scores) / len(momentum_scores) if momentum_scores else 50

    # Crypto'da RSI 50-70 sweet spot, ama 80+ overheating'in göstergesi
    if 50 <= avg_rsi <= 65:
        rsi_score = 75
    elif 40 <= avg_rsi < 50:
        rsi_score = 55
    elif avg_rsi < 30:
        rsi_score = 35
    elif avg_rsi > 75:
        rsi_score = 25  # Crypto'da overheating riski equity'den yüksek
    else:
        rsi_score = 50

    # MACD yok → o ağırlığı momentum_score'a + RSI'a paylaştır
    score = avg_mom * 0.55 + rsi_score * 0.45
    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "avg_rsi": round(avg_rsi, 1),
        "avg_momentum": round(avg_mom, 1),
        "macd_bullish_pct": None,  # crypto data layer'da MACD yok
        "label": "strong" if score >= 65 else "moderate" if score >= 45 else "weak",
    }


def _market_breadth_crypto(market_data: dict, tickers: list) -> dict:
    """Advance/Decline + EMA50 breadth — equity ile aynı, asset-agnostic."""
    advancing = 0
    declining = 0
    above_ema50 = 0

    for t in tickers:
        d = market_data.get(t, {})
        change = d.get("change_pct", 0)
        price = d.get("price", 0) or 0
        ema50 = d.get("ema50", 0) or 0

        if change > 0:
            advancing += 1
        elif change < 0:
            declining += 1
        if price > 0 and ema50 > 0 and price > ema50:
            above_ema50 += 1

    total = len(tickers) or 1
    adv_pct = advancing / total * 100
    above_ema50_pct = above_ema50 / total * 100

    score = adv_pct * 0.5 + above_ema50_pct * 0.5
    score = max(0, min(100, score))

    label = "strong" if score >= 70 else "healthy" if score >= 50 else "weak" if score >= 30 else "bearish"

    return {
        "score": round(score, 1),
        "advancing": advancing,
        "declining": declining,
        "above_ema50": above_ema50,
        "above_ema50_pct": round(above_ema50_pct, 1),
        "total": total,
        "label": label,
    }


def _build_reasoning(regime, composite, vol, trend, mom, breadth) -> str:
    parts = [f"Kantitatif skor: {composite:.1f}/100 → {regime.upper()}"]
    parts.append(
        f"BTC trend: {trend.get('btc_trend')}, alt-coin bullish %{trend.get('bullish_pct')}"
    )
    parts.append(f"Volatilite: {vol.get('label')} (ATR ort. %{vol.get('avg_atr_pct')})")
    parts.append(
        f"Momentum: {mom.get('label')} (RSI ort. {mom.get('avg_rsi')}, "
        f"momentum {mom.get('avg_momentum')})"
    )
    parts.append(
        f"Breadth: {breadth.get('advancing')}/{breadth.get('total')} yükselişte, "
        f"%{breadth.get('above_ema50_pct')} EMA50 üstünde"
    )
    return " | ".join(parts)


def _default(reason: str) -> dict:
    return {
        "regime": "unknown", "quant_score": 50, "confidence": 0,
        "components": {}, "reasoning": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────
# CryptoRegimeDetector class
# ─────────────────────────────────────────────────────────────────

class CryptoRegimeDetector(BaseRegimeDetector):
    """BTC-benchmarked, crypto-kalibre rejim algılayıcı."""

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    def detect(self, market_data: dict) -> dict:
        if not market_data:
            return _default("Veri yok")

        tickers = [k for k in market_data if not k.startswith("_")]
        if not tickers:
            return _default("Sembol yok")

        vol = _volatility_regime_crypto(market_data, tickers)
        trend = _trend_regime_crypto(market_data, tickers)
        mom = _momentum_regime_crypto(market_data, tickers)
        breadth = _market_breadth_crypto(market_data, tickers)

        # Equity ile aynı ağırlıklar
        composite = (
            trend["score"] * 0.35 +
            mom["score"] * 0.25 +
            vol["score"] * 0.25 +
            breadth["score"] * 0.15
        )

        if composite >= 65:
            regime = "bull_strong"
        elif composite >= 55:
            regime = "bull"
        elif composite >= 45:
            regime = "neutral"
        elif composite >= 35:
            regime = "bear"
        else:
            regime = "bear_strong"

        scores = [trend["score"], mom["score"], vol["score"], breadth["score"]]
        avg = sum(scores) / len(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        confidence = max(20, min(95, int(100 - variance * 0.5)))

        return {
            "regime": regime,
            "quant_score": round(composite, 1),
            "confidence": confidence,
            "components": {
                "volatility": vol,
                "trend": trend,
                "momentum": mom,
                "breadth": breadth,
            },
            "reasoning": _build_reasoning(regime, composite, vol, trend, mom, breadth),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_class": "crypto",
            "benchmark": BTC_BENCHMARK,
        }
