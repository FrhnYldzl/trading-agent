"""
crypto/data.py — Crypto market data fetcher.

Equity'deki market_scanner.py'nin (`get_market_data` / `_get_market_data_broad`)
kripto karşılığı. Aynı sözleşmeyi izler:

    {symbol: {price, open, high, low, prev_close, change_pct, volume,
              avg_volume_20d, volume_ratio, ema9, ema21, ema50, rsi14,
              atr14, atr_pct, momentum_score, signal, trend, ...},
     "_meta": {...}}

Equity'den farkları:
  - Sembol formatı "BTC/USD" (slash-separated quote pair)
  - 24/7 piyasa → market_open her zaman True
  - VWAP yok (Alpaca crypto bar'larında VWAP alanı bulunmuyor)
  - Pre-filter: PRICE filter yok (BONK $0.00002 normal), VOLUME ve
    momentum filtreleri kalır (eşikler kripto için ayrı kalibre edilir)

Tasarım kuralı: Equity broker/risk/regime modüllerine HİÇ bağımlılık yok.
Bu modül kendi başına test edilebilir, kendi başına çalışır.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

# Yumuşak import — alpaca-py SDK gerekli ama hata mesajı net olsun
try:
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False


# Equity ile aynı yardımcılar (ileride paylaşılan utils'a taşınabilir)
def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    if len(highs) < period + 1:
        return None
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return None
    return sum(trs[-period:]) / period


def _momentum_score(change_pct: float, volume_ratio: float, rsi: Optional[float]) -> int:
    """0-100 hızlı momentum skoru. Equity'deki ile aynı mantık."""
    score = 50
    score += min(20, max(-20, change_pct * 2))
    score += min(15, (volume_ratio - 1) * 10) if volume_ratio else 0
    if rsi is not None:
        if 50 < rsi < 70:
            score += 10
        elif rsi >= 70:
            score -= 5
        elif rsi < 30:
            score += 5
    return max(0, min(100, int(score)))


def get_crypto_data(
    symbols: List[str],
    api_key: str,
    secret_key: str,
    lookback_days: int = 60,
) -> dict:
    """
    Verilen sembol listesi için OHLCV + indikatör hesabı.

    Args:
        symbols: ["BTC/USD", "ETH/USD", ...] formatında.
        api_key, secret_key: Alpaca credentials.
        lookback_days: Geriye dönük gün sayısı (60 default, EMA50 için yeterli).

    Returns:
        Equity'deki get_market_data ile aynı sözleşme:
        {symbol: {...indicators...}, "_meta": {...}}

        Hata durumunda: {"_meta": {"error": "..."}, ...} (boş ticker dict)
    """
    if not _ALPACA_AVAILABLE:
        return {"_meta": {"error": "alpaca-py SDK yüklü değil"}}

    if not symbols:
        return {"_meta": {"error": "Boş sembol listesi"}}

    try:
        client = CryptoHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)

        req = CryptoBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start, end=end,
        )
        bars = client.get_crypto_bars(req)

        result: dict = {}
        for symbol in symbols:
            try:
                ticker_bars = bars[symbol]
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
                today_volume = volumes[-1]

                avg_volume_20d = sum(volumes[-20:]) / min(20, len(volumes))
                volume_ratio = today_volume / avg_volume_20d if avg_volume_20d > 0 else 0
                change_pct = (current - prev_close) / prev_close * 100 if prev_close > 0 else 0
                gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0

                ema9 = _ema(closes, 9)
                ema21 = _ema(closes, 21)
                ema50 = _ema(closes, 50)
                rsi14 = _rsi(closes, 14)
                atr14 = _atr(highs, lows, closes, 14)
                atr_pct = (atr14 / current * 100) if (atr14 and current > 0) else None

                # Trend etiketi (equity ile aynı)
                if ema9 and ema21 and ema50:
                    if ema9 > ema21 > ema50:
                        trend = "uptrend"
                    elif ema9 < ema21 < ema50:
                        trend = "downtrend"
                    else:
                        trend = "sideways"
                else:
                    trend = "unknown"

                signal = "bullish" if change_pct > 1 else "bearish" if change_pct < -1 else "neutral"
                mscore = _momentum_score(change_pct, volume_ratio, rsi14)

                result[symbol] = {
                    "price": round(current, 6),
                    "open": round(today_open, 6),
                    "high": round(today_high, 6),
                    "low": round(today_low, 6),
                    "prev_close": round(prev_close, 6),
                    "change_pct": round(change_pct, 2),
                    "gap_pct": round(gap_pct, 2),
                    "volume": today_volume,
                    "avg_volume_20d": round(avg_volume_20d, 0),
                    "volume_ratio": round(volume_ratio, 2),
                    "ema9": round(ema9, 6) if ema9 else None,
                    "ema21": round(ema21, 6) if ema21 else None,
                    "ema50": round(ema50, 6) if ema50 else None,
                    "rsi14": rsi14,
                    "atr14": round(atr14, 6) if atr14 else None,
                    "atr_pct": round(atr_pct, 2) if atr_pct else None,
                    "momentum_score": mscore,
                    "signal": signal,
                    "trend": trend,
                    "bars_count": len(ticker_bars),
                }
            except Exception as e:
                result[symbol] = {"error": str(e)}
                continue

        # Meta — equity ile aynı şema, scan_mode crypto-spesifik
        result["_meta"] = {
            "asset_class": "crypto",
            "scan_time": end.isoformat(),
            "market_open": True,  # 24/7
            "symbols_requested": len(symbols),
            "symbols_resolved": sum(1 for k in result if not k.startswith("_") and "error" not in result[k]),
        }
        return result

    except Exception as e:
        return {"_meta": {"asset_class": "crypto", "error": f"fetch hatası: {e}"}}
