"""
test_v59_crypto_smoke.py — V5.9 crypto module smoke test.

Bu test gerçek Alpaca crypto API'sine bağlanır (paper credential'larla,
sadece veri çekme — emir ya da işlem YAPMAZ). Şunları doğrular:

  1. Universe yüklenir, stablecoin'ler hariç
  2. CryptoHistoricalDataClient ile Core 10 verisi çekilir
  3. Hesaplanan indikatörler (EMA, RSI, ATR) makul aralıkta
  4. Meta dict'in şeması equity ile uyumlu

ÇALIŞTIR:
    cd server && python test_v59_crypto_smoke.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv("../.env")

PASS = "[OK]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    print(f"{tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition, detail))


# ─────────────────────────────────────────────────────────────────
# 1. Imports + universe
# ─────────────────────────────────────────────────────────────────
print("\n=== 1. Universe ===")
from crypto.universe import (
    CRYPTO_CORE, CRYPTO_EXTENDED, STABLECOINS,
    get_crypto_core_universe, get_crypto_broad_universe,
    is_stablecoin, crypto_universe_stats,
)

stats = crypto_universe_stats()
print(f"  Stats: {stats}")
check("Core sayısı = 10", stats["core_count"] == 10)
check("Stablecoin sayısı = 3 (USDC/USDT/USDG)", stats["stablecoin_count"] == 3)
check("Broad universe >= Core", stats["broad_total"] >= stats["core_count"])
check("Core tamamen Extended içinde", stats["core_in_extended"] == 10,
      f"core_in_extended={stats['core_in_extended']}")

broad = get_crypto_broad_universe()
check("Broad'da hiç stablecoin yok",
      not any(is_stablecoin(s) for s in broad),
      f"broad'da stablecoin: {[s for s in broad if is_stablecoin(s)]}")
check("BTC/USD slash format", "BTC/USD" in CRYPTO_CORE)
check("is_stablecoin('USDC/USD') True", is_stablecoin("USDC/USD"))
check("is_stablecoin('BTC/USD') False", not is_stablecoin("BTC/USD"))


# ─────────────────────────────────────────────────────────────────
# 2. Live API — Core 10 veri çekme
# ─────────────────────────────────────────────────────────────────
print("\n=== 2. Live data fetch (Alpaca crypto API) ===")

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
check("ALPACA_API_KEY mevcut", bool(api_key))
check("ALPACA_SECRET_KEY mevcut", bool(secret_key))

if not api_key or not secret_key:
    print("[!] Credentials yok, live test atlanıyor.")
    sys.exit(1 if any(not r[1] for r in results) else 0)

from crypto.data import get_crypto_data

print(f"  Fetching {len(CRYPTO_CORE)} symbols...")
md = get_crypto_data(
    symbols=CRYPTO_CORE,
    api_key=api_key,
    secret_key=secret_key,
    lookback_days=60,
)

meta = md.get("_meta", {})
check("Meta dict mevcut", bool(meta))
check("Meta asset_class = crypto", meta.get("asset_class") == "crypto")
check("Meta market_open = True (24/7)", meta.get("market_open") is True)
check("En az 8 sembol resolve edildi (Core 10'dan)",
      meta.get("symbols_resolved", 0) >= 8,
      f"resolved={meta.get('symbols_resolved')}")

# RSI / ATR aralık kontrolünde de Unicode karakter yok

# Spot-check BTC
btc = md.get("BTC/USD", {})
check("BTC/USD verisi geldi", "price" in btc)
if "price" in btc:
    print(f"  BTC: ${btc['price']:,.2f}, change {btc['change_pct']:+.2f}%, "
          f"RSI {btc.get('rsi14')}, ATR%={btc.get('atr_pct')}, trend={btc.get('trend')}")
    check("BTC price > 1000", btc["price"] > 1000)
    check("BTC change_pct sayısal", isinstance(btc["change_pct"], (int, float)))
    check("BTC RSI in [0, 100]", btc.get("rsi14") is None or 0 <= btc["rsi14"] <= 100)
    check("BTC trend etiketi mantıklı",
          btc.get("trend") in ("uptrend", "downtrend", "sideways", "unknown"))
    check("BTC momentum_score in [0, 100]", 0 <= btc.get("momentum_score", -1) <= 100)
    check("BTC ATR% > 0 (volatilite var)", btc.get("atr_pct") is None or btc["atr_pct"] > 0)

# Spot-check ETH
eth = md.get("ETH/USD", {})
if "price" in eth:
    print(f"  ETH: ${eth['price']:,.2f}, change {eth['change_pct']:+.2f}%, "
          f"RSI {eth.get('rsi14')}, trend={eth.get('trend')}")
    check("ETH/USD price > 100", eth["price"] > 100)


# ─────────────────────────────────────────────────────────────────
# 3. Şema uyumu — equity get_market_data ile aynı top-level alanlar
# ─────────────────────────────────────────────────────────────────
print("\n=== 3. Schema parity with equity ===")
expected_fields = {
    "price", "open", "high", "low", "prev_close", "change_pct",
    "volume", "avg_volume_20d", "volume_ratio", "ema9", "ema21", "ema50",
    "rsi14", "atr14", "momentum_score", "signal", "trend",
}
actual_fields = set(btc.keys()) if "price" in btc else set()
missing = expected_fields - actual_fields
check("Equity ile ortak tüm alanlar var", not missing,
      f"eksik: {missing}" if missing else "")


# ─────────────────────────────────────────────────────────────────
# Özet
# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"  Toplam: {total} | Geçen: {passed} | Kalan: {failed}")
print("=" * 60)

if failed > 0:
    print("\nBAŞARISIZ TESTLER:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
    sys.exit(1)

print("\n[OK] V5.9 crypto foundation smoke testi yeşil — universe + data layer hazır.")
sys.exit(0)
