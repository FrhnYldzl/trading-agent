"""
crypto/anomaly_impl.py — V5.10-γ: Crypto anomaly detection.

Pipeline'a eklendi: Brain'den önce çalışır, kritik anomali varsa
emergency_halt flag'i set eder → o run'da yeni LONG yapmazsız.

Detect edilen anomaliler:
  - btc_flash_dump:    BTC change_pct < -8% (24h kırılma sinyali)
  - btc_flash_pump:    BTC change_pct > +12% (overheating, yeni alım riskli)
  - extreme_volatility: ATR% > 8% (Core 10 ortalaması) — çok dalgalı
  - volume_spike:      Tek sembolde vol_ratio > 8 (manipülasyon riski)
  - market_stress:     Core 10'un >70%'i kırmızı (correlated dump)
  - rsi_extreme:       Core 10 ortalama RSI < 25 (oversold) ya da > 80 (overbought)

Çıktı:
  {
    "anomalies": [list of {type, severity, message, affected_symbols}],
    "emergency_halt": bool,    # critical anomaly varsa True → yeni long halt
    "warning_only": bool,       # sadece uyarı, halt yok
    "summary": str,
  }
"""

from typing import Optional


# Eşikler — env var ile override edilebilir
THRESHOLDS = {
    "BTC_FLASH_DUMP_PCT": -8.0,        # 24h % değişim
    "BTC_FLASH_PUMP_PCT": 12.0,
    "EXTREME_ATR_PCT": 8.0,             # Core 10 avg ATR%
    "VOLUME_SPIKE_RATIO": 8.0,          # vol_ratio
    "MARKET_STRESS_RED_PCT": 70.0,      # Core 10'un %X'i kırmızıysa
    "RSI_OVERSOLD_AVG": 25.0,
    "RSI_OVERBOUGHT_AVG": 80.0,
}


def detect_anomalies(market_data: dict) -> dict:
    """
    Market data üzerinden anomali tara.

    market_data: get_crypto_data() çıktısı (Core 10 expected)
    """
    anomalies = []
    emergency_halt = False
    tickers = [k for k in market_data if not k.startswith("_") and "error" not in market_data[k]]

    if not tickers:
        return {
            "anomalies": [],
            "emergency_halt": False,
            "warning_only": False,
            "summary": "No data",
        }

    # 1. BTC flash dump/pump (en kritik — emergency halt tetikleyici)
    btc = market_data.get("BTC/USD", {})
    btc_change = btc.get("change_pct")
    if btc_change is not None:
        if btc_change <= THRESHOLDS["BTC_FLASH_DUMP_PCT"]:
            anomalies.append({
                "type": "btc_flash_dump",
                "severity": "critical",
                "message": f"BTC %{btc_change:.2f} — flash dump! Yeni long halt.",
                "affected_symbols": ["BTC/USD"],
            })
            emergency_halt = True
        elif btc_change >= THRESHOLDS["BTC_FLASH_PUMP_PCT"]:
            anomalies.append({
                "type": "btc_flash_pump",
                "severity": "warning",
                "message": f"BTC %+{btc_change:.2f} — overheating, yeni alım riskli.",
                "affected_symbols": ["BTC/USD"],
            })

    # 2. Extreme volatility (Core ortalaması)
    atrs = [d.get("atr_pct", 0) for t, d in market_data.items()
            if not t.startswith("_") and d.get("atr_pct")]
    if atrs:
        avg_atr = sum(atrs) / len(atrs)
        if avg_atr > THRESHOLDS["EXTREME_ATR_PCT"]:
            anomalies.append({
                "type": "extreme_volatility",
                "severity": "warning",
                "message": f"Core 10 ATR ort. %{avg_atr:.2f} — extreme vol, conservative mode öneriliyor.",
                "affected_symbols": tickers,
            })

    # 3. Volume spike — tek sembolde
    for t in tickers:
        d = market_data.get(t, {})
        vol_ratio = d.get("volume_ratio", 0) or 0
        if vol_ratio > THRESHOLDS["VOLUME_SPIKE_RATIO"]:
            anomalies.append({
                "type": "volume_spike",
                "severity": "warning",
                "message": f"{t} vol×{vol_ratio:.1f} — catalyst yoksa manipülasyon riski.",
                "affected_symbols": [t],
            })

    # 4. Market stress — Core 10'un çoğu kırmızı
    if tickers:
        red_count = sum(1 for t in tickers if (market_data[t].get("change_pct") or 0) < 0)
        red_pct = red_count / len(tickers) * 100
        if red_pct > THRESHOLDS["MARKET_STRESS_RED_PCT"]:
            anomalies.append({
                "type": "market_stress",
                "severity": "warning",
                "message": f"%{red_pct:.0f} Core 10 kırmızıda — correlated risk-off, defensive mode.",
                "affected_symbols": tickers,
            })

    # 5. RSI extremes (Core ortalaması)
    rsis = [d.get("rsi14") for t, d in market_data.items()
            if not t.startswith("_") and d.get("rsi14") is not None]
    if rsis:
        avg_rsi = sum(rsis) / len(rsis)
        if avg_rsi < THRESHOLDS["RSI_OVERSOLD_AVG"]:
            anomalies.append({
                "type": "rsi_oversold_extreme",
                "severity": "info",
                "message": f"Core 10 RSI ort. {avg_rsi:.1f} — bottom-fishing fırsatı (dikkatli).",
                "affected_symbols": tickers,
            })
        elif avg_rsi > THRESHOLDS["RSI_OVERBOUGHT_AVG"]:
            anomalies.append({
                "type": "rsi_overbought_extreme",
                "severity": "warning",
                "message": f"Core 10 RSI ort. {avg_rsi:.1f} — overheating, yeni alım yapma.",
                "affected_symbols": tickers,
            })

    warning_only = bool(anomalies) and not emergency_halt
    severity_counts = {
        "critical": sum(1 for a in anomalies if a["severity"] == "critical"),
        "warning": sum(1 for a in anomalies if a["severity"] == "warning"),
        "info": sum(1 for a in anomalies if a["severity"] == "info"),
    }

    if emergency_halt:
        summary = f"⛔ EMERGENCY HALT — {len(anomalies)} anomali ({severity_counts})."
    elif warning_only:
        summary = f"⚠ {len(anomalies)} uyarı tespit edildi ({severity_counts})."
    else:
        summary = "✓ Anomali yok, normal piyasa."

    return {
        "anomalies": anomalies,
        "emergency_halt": emergency_halt,
        "warning_only": warning_only,
        "summary": summary,
        "severity_counts": severity_counts,
    }
