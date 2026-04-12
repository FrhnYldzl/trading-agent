"""
market_scanner.py — Gelismis Piyasa Tarayici (V2)

Alpaca Data API'dan fiyat verisi ceker ve profesyonel teknik indikatörler hesaplar.
Ross Cameron tarzi momentum trading icin optimize edilmistir.

Hesaplanan indikatörler:
  - EMA 9 / 21 / 50
  - RSI 14
  - ATR 14 (Average True Range — volatilite)
  - Volume Ratio (bugünkü hacim / 20 günlük ortalama)
  - Momentum Score (0-100, bilesik skor)
  - Gap % (önceki kapanisa göre acilis farki)
  - VWAP yaklasimi (günlük)
  - Göreceli Güc (sektör/endeks karsılastırması)

Harici kütüphane gerekmez — hesaplamalar saf Python ile yapılır.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)
_env_vals = dotenv_values(_env_path)

def _get(key): return os.getenv(key) or _env_vals.get(key, "")

# ── Izleme Listesi ────────────────────────────────────────────────
# Momentum trading icin: buyuk hacimli, likit hisseler + ETF'ler
WATCHLIST = [
    # Mega-cap tech (yüksek momentum potansiyeli)
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "AMD",
    # ETF'ler (piyasa rejimi tespiti icin)
    "SPY", "QQQ",
    # Ek momentum adaylari
    "NFLX", "CRM", "AVGO", "COIN", "MARA",
]

# Benchmark — rejim algilama icin
BENCHMARK = "SPY"

# ─────────────────────────────────────────────────────────────────

def get_market_data() -> dict:
    """
    Tüm watchlist icin son 60 günlük OHLCV verisi + gelismis teknik indikatörler döndürür.

    Returns:
        {
          "AAPL": {
            "price": 190.5,
            "open": 188.0,
            "high": 191.2,
            "low": 187.5,
            "prev_close": 187.0,
            "change_pct": 1.87,
            "gap_pct": 0.53,
            "volume": 45_000_000,
            "avg_volume_20d": 38_000_000,
            "volume_ratio": 1.18,
            "ema9": 188.2,
            "ema21": 185.0,
            "ema50": 182.3,
            "rsi14": 58.3,
            "atr14": 3.45,
            "atr_pct": 1.81,
            "vwap": 189.8,
            "momentum_score": 72,
            "signal": "bullish",
            "trend": "uptrend",
            "bars_5d": [...],
          },
          "_meta": {
            "market_open": true,
            "scan_time": "2024-...",
            "regime": "bullish",
            "spy_change": 0.8,
            "vix_proxy": 15.2,
          }
        }
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(
            api_key=_get("ALPACA_API_KEY"),
            secret_key=_get("ALPACA_SECRET_KEY"),
        )

        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=90)  # EMA50 + ATR icin yeterli veri

        req = StockBarsRequest(
            symbol_or_symbols=WATCHLIST,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex",
        )

        bars = client.get_stock_bars(req)
        result = {}

        # Önce SPY verisini hesapla (rejim algilama icin)
        spy_change = 0.0

        for ticker in WATCHLIST:
            try:
                ticker_bars = bars[ticker]
                if len(ticker_bars) < 5:
                    continue

                opens   = [float(b.open) for b in ticker_bars]
                highs   = [float(b.high) for b in ticker_bars]
                lows    = [float(b.low) for b in ticker_bars]
                closes  = [float(b.close) for b in ticker_bars]
                volumes = [float(b.volume) for b in ticker_bars]

                current    = closes[-1]
                prev_close = closes[-2]
                today_open = opens[-1]
                today_high = highs[-1]
                today_low  = lows[-1]

                change_pct = round((current - prev_close) / prev_close * 100, 2)
                gap_pct    = round((today_open - prev_close) / prev_close * 100, 2)

                # EMA'lar
                ema9  = _ema(closes, 9)
                ema21 = _ema(closes, 21)
                ema50 = _ema(closes, 50)

                # RSI
                rsi14 = _rsi(closes, 14)

                # ATR (volatilite ölcümü)
                atr14 = _atr(highs, lows, closes, 14)
                atr_pct = round(atr14 / current * 100, 2) if current > 0 else 0

                # Volume analizi
                avg_vol_20 = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 0
                vol_ratio  = round(volumes[-1] / avg_vol_20, 2) if avg_vol_20 > 0 else 0

                # VWAP yaklasimi (günlük: typical_price * volume / total_volume)
                vwap = _vwap_approx(highs[-5:], lows[-5:], closes[-5:], volumes[-5:])

                # Trend tespiti
                trend = _detect_trend(closes, ema9, ema21, ema50)

                # Sinyal
                signal = _generate_signal(
                    ema9, ema21, ema50, rsi14, vol_ratio, change_pct, gap_pct, trend
                )

                # Momentum Score (0-100) — bilesik skor
                momentum_score = _calc_momentum_score(
                    change_pct, gap_pct, vol_ratio, rsi14,
                    ema9, ema21, ema50, atr_pct, trend
                )

                if ticker == BENCHMARK:
                    spy_change = change_pct

                result[ticker] = {
                    "price":         round(current, 2),
                    "open":          round(today_open, 2),
                    "high":          round(today_high, 2),
                    "low":           round(today_low, 2),
                    "prev_close":    round(prev_close, 2),
                    "change_pct":    change_pct,
                    "gap_pct":       gap_pct,
                    "volume":        int(volumes[-1]),
                    "avg_volume_20d": int(avg_vol_20),
                    "volume_ratio":  vol_ratio,
                    "ema9":          round(ema9, 2),
                    "ema21":         round(ema21, 2),
                    "ema50":         round(ema50, 2),
                    "rsi14":         round(rsi14, 1),
                    "atr14":         round(atr14, 2),
                    "atr_pct":       atr_pct,
                    "vwap":          round(vwap, 2),
                    "momentum_score": momentum_score,
                    "signal":        signal,
                    "trend":         trend,
                    "bars_5d":       [round(c, 2) for c in closes[-5:]],
                    "relative_strength": round(change_pct - spy_change, 2),
                }
            except Exception:
                continue

        # Meta bilgi
        market_open = is_market_open()
        regime = _detect_regime(result)

        result["_meta"] = {
            "market_open":  market_open,
            "scan_time":    datetime.now(timezone.utc).isoformat(),
            "regime":       regime,
            "spy_change":   spy_change,
            "total_stocks": len([k for k in result if not k.startswith("_")]),
            "bullish_count": len([k for k, v in result.items() if isinstance(v, dict) and v.get("signal") == "strong_buy"]),
        }

        return result

    except Exception as e:
        return {"error": str(e)}


# ── Gelismis Teknik Indikatör Hesaplamalari ──────────────────────

def _ema(prices: list, period: int) -> float:
    """Exponential Moving Average."""
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _rsi(prices: list, period: int = 14) -> float:
    """Relative Strength Index (Wilder's smoothing)."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]

    # Ilk ortalama
    gains  = [max(d, 0) for d in deltas[:period]]
    losses = [max(-d, 0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder's smoothing (daha dogru RSI)
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Average True Range — volatilite ölcümü."""
    if len(closes) < 2:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1]),
        )
        trs.append(tr)
    if not trs:
        return 0.0
    # Wilder's smoothing for ATR
    atr = sum(trs[:period]) / min(len(trs), period)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _vwap_approx(highs: list, lows: list, closes: list, volumes: list) -> float:
    """VWAP yaklasimi (son N bar icin)."""
    if not volumes or sum(volumes) == 0:
        return closes[-1] if closes else 0
    total_pv = sum(
        ((h + l + c) / 3) * v
        for h, l, c, v in zip(highs, lows, closes, volumes)
    )
    return total_pv / sum(volumes)


def _detect_trend(closes: list, ema9: float, ema21: float, ema50: float) -> str:
    """Trend tespiti: strong_uptrend, uptrend, sideways, downtrend, strong_downtrend."""
    price = closes[-1]
    if price > ema9 > ema21 > ema50:
        return "strong_uptrend"
    elif price > ema21 and ema9 > ema21:
        return "uptrend"
    elif price < ema9 < ema21 < ema50:
        return "strong_downtrend"
    elif price < ema21 and ema9 < ema21:
        return "downtrend"
    return "sideways"


def _generate_signal(ema9, ema21, ema50, rsi, vol_ratio, change_pct, gap_pct, trend):
    """
    Gelismis sinyal üretimi — Ross Cameron kriterleri:
    - strong_buy : momentum + hacim patlamasi + trend uyumu
    - buy        : teknik olarak uygun, konfirmasyona yakin
    - neutral    : belirsiz, bekle
    - sell       : satis sinyali
    - strong_sell: acil cikis
    """
    score = 0

    # Trend uyumu (+3 / -3)
    if trend in ("strong_uptrend",):
        score += 3
    elif trend == "uptrend":
        score += 2
    elif trend == "downtrend":
        score -= 2
    elif trend == "strong_downtrend":
        score -= 3

    # RSI (momentum bandı)
    if 40 <= rsi <= 65:       # Ideal momentum bölgesi
        score += 2
    elif 30 <= rsi < 40:      # Dip alim potansiyeli
        score += 1
    elif rsi > 80:            # Asiri alim — tehlike
        score -= 2
    elif rsi < 25:            # Asiri satim — potansiyel bounce
        score += 1

    # Hacim konfirmasyonu (+2 / -1)
    if vol_ratio >= 2.0:      # Hacim patlamasi (Ross Cameron kriteri!)
        score += 3
    elif vol_ratio >= 1.3:
        score += 1
    elif vol_ratio < 0.5:
        score -= 1

    # Gap & Go (Ross Cameron ana stratejisi)
    if gap_pct >= 4.0 and vol_ratio >= 1.5:
        score += 3            # Klasik Gap & Go setup
    elif gap_pct >= 2.0 and vol_ratio >= 1.2:
        score += 2
    elif gap_pct <= -4.0:
        score -= 2            # Gap down — dikkat

    # Günlük degisim
    if change_pct >= 3.0:
        score += 1
    elif change_pct <= -3.0:
        score -= 1

    # Sinyal haritalama
    if score >= 6:
        return "strong_buy"
    elif score >= 3:
        return "buy"
    elif score <= -4:
        return "strong_sell"
    elif score <= -2:
        return "sell"
    return "neutral"


def _calc_momentum_score(change_pct, gap_pct, vol_ratio, rsi, ema9, ema21, ema50, atr_pct, trend):
    """
    Bilesik momentum skoru (0-100).
    Ross Cameron'in odaklandigi 4 faktör:
    1. Fiyat hareketi (change + gap)
    2. Hacim gücü (volume ratio)
    3. Trend uyumu (EMA yapilanmasi)
    4. Volatilite (ATR — hareket potansiyeli)
    """
    score = 50  # Baz

    # 1. Fiyat hareketi (max +/- 20)
    score += min(max(change_pct * 3, -20), 20)
    score += min(max(gap_pct * 2, -10), 10)

    # 2. Hacim gücü (max +/- 15)
    if vol_ratio >= 3.0:
        score += 15
    elif vol_ratio >= 2.0:
        score += 10
    elif vol_ratio >= 1.3:
        score += 5
    elif vol_ratio < 0.5:
        score -= 10

    # 3. Trend uyumu (max +/- 15)
    trend_map = {
        "strong_uptrend": 15,
        "uptrend": 8,
        "sideways": 0,
        "downtrend": -8,
        "strong_downtrend": -15,
    }
    score += trend_map.get(trend, 0)

    # 4. Volatilite bonus (hareket potansiyeli)
    if 1.5 <= atr_pct <= 4.0:   # Ideal volatilite bandi
        score += 5
    elif atr_pct > 6.0:         # Cok volatil — riskli
        score -= 5

    # RSI ayarlama
    if rsi > 80:
        score -= 10  # Asiri alim penalti
    elif rsi < 20:
        score -= 5   # Asiri satim — belirsiz

    return max(0, min(100, round(score)))


def _detect_regime(market_data: dict) -> str:
    """
    Genel piyasa rejimi algilamasi.
    SPY + QQQ + genel momentum skorlarina bakarak:
    - bull_strong : güclu boga
    - bull        : boga
    - neutral     : yatay / belirsiz
    - bear        : ayi
    - bear_strong : güclu ayi
    """
    spy = market_data.get("SPY", {})
    qqq = market_data.get("QQQ", {})

    if not spy or not qqq:
        return "unknown"

    spy_change = spy.get("change_pct", 0)
    qqq_change = qqq.get("change_pct", 0)
    spy_trend  = spy.get("trend", "sideways")
    qqq_trend  = qqq.get("trend", "sideways")

    # Ortalama degisim
    avg_change = (spy_change + qqq_change) / 2

    # Tüm hisselerin momentum skoru ortalaması
    scores = [
        v.get("momentum_score", 50)
        for k, v in market_data.items()
        if isinstance(v, dict) and not k.startswith("_") and "momentum_score" in v
    ]
    avg_momentum = sum(scores) / len(scores) if scores else 50

    if avg_change > 1.0 and avg_momentum > 65 and "uptrend" in spy_trend:
        return "bull_strong"
    elif avg_change > 0.3 and avg_momentum > 55:
        return "bull"
    elif avg_change < -1.0 and avg_momentum < 35 and "downtrend" in spy_trend:
        return "bear_strong"
    elif avg_change < -0.3 and avg_momentum < 45:
        return "bear"
    return "neutral"


def is_market_open() -> bool:
    """ABD piyasasi acik mi? (UTC saatine göre basit kontrol)"""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Cumartesi / Pazar
        return False
    market_open  = now.replace(hour=13, minute=30, second=0)  # 13:30 UTC = 09:30 ET
    market_close = now.replace(hour=20, minute=0,  second=0)  # 20:00 UTC = 16:00 ET
    return market_open <= now <= market_close


def is_premarket() -> bool:
    """Pre-market saatleri mi? (04:00-09:30 ET = 08:00-13:30 UTC)"""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    pre_open  = now.replace(hour=8,  minute=0,  second=0)
    mkt_open  = now.replace(hour=13, minute=30, second=0)
    return pre_open <= now < mkt_open
