"""
market_scanner.py — Gelismis Piyasa Tarayici (V3)

Alpaca Data API'dan fiyat verisi ceker ve profesyonel teknik indikatörler hesaplar.
Ross Cameron tarzi momentum trading icin optimize edilmistir.

Hesaplanan indikatörler:
  - EMA 9 / 21 / 50
  - RSI 14
  - ATR 14 (Average True Range — volatilite)
  - MACD (12/26/9) + Histogram + Sinyal
  - Bollinger Bands (20, 2σ)
  - Volume Ratio (bugünkü hacim / 20 günlük ortalama)
  - Momentum Score (0-100, bilesik skor)
  - Gap % (önceki kapanisa göre acilis farki)
  - VWAP yaklasimi (günlük)
  - Göreceli Güc (sektör/endeks karsılastırması)

Harici kütüphane gerekmez — hesaplamalar saf Python ile yapılır.
"""

import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)
_env_vals = dotenv_values(_env_path)

def _get(key): return os.getenv(key) or _env_vals.get(key, "")

from config import (
    WATCHLIST as _CFG_WATCHLIST,
    BENCHMARK as _CFG_BENCHMARK,
    LOOKBACK_DAYS,
    SIGNAL_GAP_THRESHOLD, SIGNAL_VOLUME_THRESHOLD,
)

# Config'den al
WATCHLIST = _CFG_WATCHLIST
BENCHMARK = _CFG_BENCHMARK

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
        start = end - timedelta(days=LOOKBACK_DAYS)

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

                # V3: MACD (12, 26, 9)
                macd_data = _macd(closes)

                # V3: Bollinger Bands (20, 2σ)
                bb_data = _bollinger_bands(closes)

                # Trend tespiti
                trend = _detect_trend(closes, ema9, ema21, ema50)

                # Sinyal (V3: MACD + Bollinger dahil)
                signal = _generate_signal(
                    ema9, ema21, ema50, rsi14, vol_ratio, change_pct, gap_pct, trend,
                    macd_data=macd_data, bb_data=bb_data, current_price=current,
                )

                # Momentum Score (0-100) — bilesik skor
                momentum_score = _calc_momentum_score(
                    change_pct, gap_pct, vol_ratio, rsi14,
                    ema9, ema21, ema50, atr_pct, trend,
                    macd_data=macd_data, bb_data=bb_data, current_price=current,
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
                    "macd":          macd_data["macd"],
                    "macd_signal":   macd_data["signal"],
                    "macd_histogram": macd_data["histogram"],
                    "macd_cross":    macd_data["cross"],
                    "bb_upper":      bb_data["upper"],
                    "bb_middle":     bb_data["middle"],
                    "bb_lower":      bb_data["lower"],
                    "bb_width":      bb_data["width"],
                    "bb_position":   bb_data["position"],
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


def _macd(closes: list, fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict:
    """
    MACD (Moving Average Convergence Divergence).
    Returns: macd line, signal line, histogram, cross direction.
    """
    if len(closes) < slow + signal_period:
        return {"macd": 0, "signal": 0, "histogram": 0, "cross": "none"}

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = round(ema_fast - ema_slow, 4)

    # MACD serisini hesapla (signal line için)
    macd_series = []
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    ef = sum(closes[:fast]) / fast
    es = sum(closes[:slow]) / slow
    for i in range(slow, len(closes)):
        ef = closes[i] * k_fast + ef * (1 - k_fast)
        es = closes[i] * k_slow + es * (1 - k_slow)
        macd_series.append(ef - es)

    # Signal line (EMA of MACD)
    if len(macd_series) >= signal_period:
        k_sig = 2 / (signal_period + 1)
        sig = sum(macd_series[:signal_period]) / signal_period
        for val in macd_series[signal_period:]:
            sig = val * k_sig + sig * (1 - k_sig)
        signal_line = round(sig, 4)
    else:
        signal_line = 0

    histogram = round(macd_line - signal_line, 4)

    # Cross detection
    cross = "none"
    if len(macd_series) >= 2:
        prev_hist = macd_series[-2] - signal_line if len(macd_series) > 1 else 0
        if histogram > 0 and prev_hist <= 0:
            cross = "bullish_cross"
        elif histogram < 0 and prev_hist >= 0:
            cross = "bearish_cross"

    return {
        "macd": round(macd_line, 2),
        "signal": round(signal_line, 2),
        "histogram": round(histogram, 2),
        "cross": cross,
    }


def _bollinger_bands(closes: list, period: int = 20, std_dev: float = 2.0) -> dict:
    """
    Bollinger Bands (20, 2σ).
    Returns: upper, middle, lower, width, position (0-1 where price sits).
    """
    if len(closes) < period:
        price = closes[-1] if closes else 0
        return {"upper": price, "middle": price, "lower": price, "width": 0, "position": 0.5}

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = round(middle + std_dev * std, 2)
    lower = round(middle - std_dev * std, 2)
    middle = round(middle, 2)

    # Band width (volatilite ölçüsü)
    width = round((upper - lower) / middle * 100, 2) if middle > 0 else 0

    # Position: fiyat bandın neresinde? (0=alt, 0.5=orta, 1=üst)
    current = closes[-1]
    band_range = upper - lower
    position = round((current - lower) / band_range, 2) if band_range > 0 else 0.5

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "width": width,
        "position": max(0, min(1, position)),
    }


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


def _generate_signal(ema9, ema21, ema50, rsi, vol_ratio, change_pct, gap_pct, trend,
                     macd_data=None, bb_data=None, current_price=0):
    """
    V3 Gelismis sinyal üretimi — Ross Cameron + MACD + Bollinger confluence:
    - strong_buy : momentum + hacim + trend + MACD bullish + BB alt bant
    - buy        : teknik uyum + en az 2 konfirmasyon
    - neutral    : belirsiz
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
    if 40 <= rsi <= 65:
        score += 2
    elif 30 <= rsi < 40:
        score += 1
    elif rsi > 80:
        score -= 2
    elif rsi < 25:
        score += 1

    # Hacim konfirmasyonu
    if vol_ratio >= SIGNAL_VOLUME_THRESHOLD:
        score += 3
    elif vol_ratio >= 1.3:
        score += 1
    elif vol_ratio < 0.5:
        score -= 1

    # Gap & Go
    if gap_pct >= SIGNAL_GAP_THRESHOLD and vol_ratio >= 1.5:
        score += 3
    elif gap_pct >= 2.0 and vol_ratio >= 1.2:
        score += 2
    elif gap_pct <= -SIGNAL_GAP_THRESHOLD:
        score -= 2

    # Günlük degisim
    if change_pct >= 3.0:
        score += 1
    elif change_pct <= -3.0:
        score -= 1

    # V3: MACD Confluence (+2 / -2)
    if macd_data:
        if macd_data["cross"] == "bullish_cross":
            score += 2
        elif macd_data["cross"] == "bearish_cross":
            score -= 2
        elif macd_data["histogram"] > 0:
            score += 1
        elif macd_data["histogram"] < 0:
            score -= 1

    # V3: Bollinger Bands Confluence (+2 / -2)
    if bb_data and current_price > 0:
        bb_pos = bb_data["position"]
        if bb_pos <= 0.1:    # Fiyat alt banda yakin — bounce potansiyeli
            score += 2
        elif bb_pos >= 0.9:  # Fiyat ust banda yakin — geri cekilme riski
            score -= 1
        if bb_data["width"] > 8:  # Genis band = yüksek volatilite = firsat
            score += 1

    # Sinyal haritalama
    if score >= 7:
        return "strong_buy"
    elif score >= 3:
        return "buy"
    elif score <= -5:
        return "strong_sell"
    elif score <= -2:
        return "sell"
    return "neutral"


def _calc_momentum_score(change_pct, gap_pct, vol_ratio, rsi, ema9, ema21, ema50, atr_pct, trend,
                         macd_data=None, bb_data=None, current_price=0):
    """
    V3 Bilesik momentum skoru (0-100).
    6 faktör (Ross Cameron + MACD + Bollinger):
    1. Fiyat hareketi (change + gap)
    2. Hacim gücü (volume ratio)
    3. Trend uyumu (EMA yapilanmasi)
    4. Volatilite (ATR)
    5. MACD momentum
    6. Bollinger position
    """
    score = 50

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
        "strong_uptrend": 15, "uptrend": 8, "sideways": 0,
        "downtrend": -8, "strong_downtrend": -15,
    }
    score += trend_map.get(trend, 0)

    # 4. Volatilite
    if 1.5 <= atr_pct <= 4.0:
        score += 5
    elif atr_pct > 6.0:
        score -= 5

    # RSI ayarlama
    if rsi > 80:
        score -= 10
    elif rsi < 20:
        score -= 5

    # 5. V3: MACD momentum (+/- 8)
    if macd_data:
        if macd_data["cross"] == "bullish_cross":
            score += 8
        elif macd_data["cross"] == "bearish_cross":
            score -= 8
        elif macd_data["histogram"] > 0:
            score += 3
        elif macd_data["histogram"] < 0:
            score -= 3

    # 6. V3: Bollinger position (+/- 5)
    if bb_data:
        bb_pos = bb_data["position"]
        if bb_pos <= 0.15:   # Alt bant — oversold bounce
            score += 5
        elif bb_pos >= 0.85: # Üst bant — overbought
            score -= 3

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


# ═══════════════════════════════════════════════════════════════
# V3: Multi-Timeframe Analiz
# ═══════════════════════════════════════════════════════════════

def get_multi_timeframe(tickers: list = None) -> dict:
    """
    Birden fazla zaman diliminde teknik analiz.
    1 saatlik, 4 saatlik ve günlük mumlar ile timeframe confluence.

    Returns:
        {
          "AAPL": {
            "1h": {"ema9": ..., "rsi14": ..., "trend": ..., "macd": ...},
            "4h": {"ema9": ..., "rsi14": ..., "trend": ..., "macd": ...},
            "1d": {"ema9": ..., "rsi14": ..., "trend": ..., "macd": ...},
            "confluence": "strong_bullish" | "bullish" | "mixed" | "bearish" | "strong_bearish",
            "confluence_score": 85,
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

        symbols = tickers or WATCHLIST
        end = datetime.now(timezone.utc)
        result = {}

        timeframes = [
            ("1h", TimeFrame.Hour, timedelta(days=10)),
            ("4h", TimeFrame(4, "Hour"), timedelta(days=30)),
            ("1d", TimeFrame.Day, timedelta(days=LOOKBACK_DAYS)),
        ]

        for tf_label, tf_enum, lookback in timeframes:
            try:
                req = StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=tf_enum,
                    start=end - lookback,
                    end=end,
                    feed="iex",
                )
                bars = client.get_stock_bars(req)

                for ticker in symbols:
                    try:
                        ticker_bars = bars[ticker]
                        if len(ticker_bars) < 5:
                            continue

                        closes = [float(b.close) for b in ticker_bars]
                        highs = [float(b.high) for b in ticker_bars]
                        lows = [float(b.low) for b in ticker_bars]

                        ema9 = _ema(closes, 9)
                        ema21 = _ema(closes, 21)
                        ema50 = _ema(closes, min(50, len(closes)))
                        rsi14 = _rsi(closes, 14)
                        macd_data = _macd(closes)
                        trend = _detect_trend(closes, ema9, ema21, ema50)

                        if ticker not in result:
                            result[ticker] = {}

                        result[ticker][tf_label] = {
                            "ema9": round(ema9, 2),
                            "ema21": round(ema21, 2),
                            "rsi14": round(rsi14, 1),
                            "trend": trend,
                            "macd": macd_data["macd"],
                            "macd_histogram": macd_data["histogram"],
                            "macd_cross": macd_data["cross"],
                            "price": round(closes[-1], 2),
                        }
                    except Exception:
                        continue
            except Exception:
                continue

        # Confluence hesapla
        for ticker, tf_data in result.items():
            result[ticker]["confluence"] = _calc_confluence(tf_data)

        return result

    except Exception as e:
        return {"error": str(e)}


def _calc_confluence(tf_data: dict) -> dict:
    """
    Timeframe confluence: tüm zaman dilimlerindeki trend uyumunu ölç.
    Üç TF de aynı yönde = strong, iki TF = moderate, karışık = mixed.
    """
    trend_scores = {"strong_uptrend": 2, "uptrend": 1, "sideways": 0, "downtrend": -1, "strong_downtrend": -2}
    total = 0
    count = 0

    for tf in ("1h", "4h", "1d"):
        if tf in tf_data:
            trend = tf_data[tf].get("trend", "sideways")
            total += trend_scores.get(trend, 0)
            # MACD bonus
            hist = tf_data[tf].get("macd_histogram", 0)
            if hist > 0:
                total += 0.5
            elif hist < 0:
                total -= 0.5
            count += 1

    if count == 0:
        return {"direction": "unknown", "score": 50, "alignment": 0}

    avg = total / count
    # -3 ile +3 arası → 0-100'e çevir
    score = round(max(0, min(100, (avg + 3) / 6 * 100)))

    if avg >= 2.0:
        direction = "strong_bullish"
    elif avg >= 1.0:
        direction = "bullish"
    elif avg <= -2.0:
        direction = "strong_bearish"
    elif avg <= -1.0:
        direction = "bearish"
    else:
        direction = "mixed"

    return {"direction": direction, "score": score, "alignment": round(avg, 1)}


# ═══════════════════════════════════════════════════════════════
# V3: Korelasyon Matrisi
# ═══════════════════════════════════════════════════════════════

def get_correlation_matrix(tickers: list = None) -> dict:
    """
    Hisseler arası korelasyon matrisi.
    Günlük getirilerin Pearson korelasyonunu hesaplar.

    Returns:
        {
          "matrix": {"AAPL": {"MSFT": 0.85, "NVDA": 0.72, ...}, ...},
          "high_correlations": [{"pair": "AAPL-MSFT", "corr": 0.85}, ...],
          "diversification_score": 65,
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

        symbols = tickers or [t for t in WATCHLIST if t not in ("SPY", "QQQ")]
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=60)

        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start, end=end, feed="iex",
        )
        bars = client.get_stock_bars(req)

        # Günlük getiri hesapla
        returns = {}
        for ticker in symbols:
            try:
                ticker_bars = bars[ticker]
                closes = [float(b.close) for b in ticker_bars]
                if len(closes) < 10:
                    continue
                daily_returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                returns[ticker] = daily_returns
            except Exception:
                continue

        # Korelasyon matrisi
        tickers_with_data = list(returns.keys())
        matrix = {}
        high_corrs = []

        for i, t1 in enumerate(tickers_with_data):
            matrix[t1] = {}
            for j, t2 in enumerate(tickers_with_data):
                if i == j:
                    matrix[t1][t2] = 1.0
                    continue
                corr = _pearson_correlation(returns[t1], returns[t2])
                matrix[t1][t2] = corr
                if i < j and abs(corr) >= 0.7:
                    high_corrs.append({"pair": f"{t1}-{t2}", "corr": corr})

        high_corrs.sort(key=lambda x: abs(x["corr"]), reverse=True)

        # Diversifikasyon skoru: düşük korelasyon = yüksek skor
        if len(high_corrs) > 0:
            avg_high = sum(abs(c["corr"]) for c in high_corrs) / len(high_corrs)
            div_score = round(max(0, (1 - avg_high) * 100))
        else:
            div_score = 90  # Az korelasyon = iyi

        return {
            "matrix": matrix,
            "high_correlations": high_corrs[:10],
            "diversification_score": div_score,
            "tickers": tickers_with_data,
        }

    except Exception as e:
        return {"error": str(e), "matrix": {}, "high_correlations": [], "diversification_score": 0}


def _pearson_correlation(x: list, y: list) -> float:
    """Pearson korelasyon katsayısı hesapla."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0

    x = x[-n:]
    y = y[-n:]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if den_x == 0 or den_y == 0:
        return 0.0

    return round(num / (den_x * den_y), 2)
