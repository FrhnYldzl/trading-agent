"""
test_v58_regression.py — V5.8 refactor sıfır-davranış-değişikliği regression testi.

Garanti edilen şey: equity adapter'larının çıktısı, mevcut modülleri doğrudan
çağırmakla birebir aynıdır. Tek satır farklılık = refactor başarısız sayılır.

Çalıştır:
    cd server && python test_v58_regression.py
"""

import json
import sys
from pathlib import Path

# Test runner ayarı
PASS = "[OK]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    print(f"{tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition, detail))


# ─────────────────────────────────────────────────────────────────
# 1. Import sanity — yeni paketler hatasız yüklensin
# ─────────────────────────────────────────────────────────────────
print("\n=== 1. Import sanity ===")
try:
    from core import (
        AssetClass, BaseBroker, BaseRiskManager,
        BaseBrain, BaseRegimeDetector, BaseScheduler,
    )
    check("core/ paketi import edildi", True)
except Exception as e:
    check("core/ paketi import edildi", False, str(e))
    sys.exit(1)

try:
    from equity import (
        EquityBrokerAdapter, EquityRiskAdapter, EquityBrainAdapter,
        EquityRegimeAdapter, EquitySchedulerAdapter,
    )
    check("equity/ paketi import edildi", True)
except Exception as e:
    check("equity/ paketi import edildi", False, str(e))
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────
# 2. AssetClass enum kontrolü
# ─────────────────────────────────────────────────────────────────
print("\n=== 2. AssetClass enum ===")
check("EQUITY.is_24_7 = False", AssetClass.EQUITY.is_24_7 is False)
check("CRYPTO.is_24_7 = True", AssetClass.CRYPTO.is_24_7 is True)
check("EQUITY.supports_pdt = True", AssetClass.EQUITY.supports_pdt is True)
check("CRYPTO.supports_pdt = False", AssetClass.CRYPTO.supports_pdt is False)


# ─────────────────────────────────────────────────────────────────
# 3. Adapter asset_class property
# ─────────────────────────────────────────────────────────────────
print("\n=== 3. Adapter asset_class identity ===")
# Broker/Risk init'te env okur; testler için lazy
risk = EquityRiskAdapter()
brain = EquityBrainAdapter()
regime = EquityRegimeAdapter()
sched = EquitySchedulerAdapter()
check("EquityRiskAdapter.asset_class == EQUITY", risk.asset_class == AssetClass.EQUITY)
check("EquityBrainAdapter.asset_class == EQUITY", brain.asset_class == AssetClass.EQUITY)
check("EquityRegimeAdapter.asset_class == EQUITY", regime.asset_class == AssetClass.EQUITY)
check("EquitySchedulerAdapter.asset_class == EQUITY", sched.asset_class == AssetClass.EQUITY)


# ─────────────────────────────────────────────────────────────────
# 4. Regime detector — birebir eşitlik
# ─────────────────────────────────────────────────────────────────
print("\n=== 4. Regime detector regression ===")
from market_scanner import get_market_data
from regime_detector import detect_regime

print("[*] Live market data çekiliyor (broad scan)...")
md = get_market_data()
check("market_data fetched", "_meta" in md, f"{len(md)} ticker, scan_mode={md.get('_meta', {}).get('scan_mode')}")

old_regime = detect_regime(md)
new_regime = regime.detect(md)
# Timestamp hariç byte-identical olmalı
old_no_ts = {k: v for k, v in old_regime.items() if k != "timestamp"}
new_no_ts = {k: v for k, v in new_regime.items() if k != "timestamp"}
check(
    "regime adapter çıktısı eski koda birebir eşit",
    old_no_ts == new_no_ts,
    f"old={old_regime.get('regime')}, new={new_regime.get('regime')}",
)


# ─────────────────────────────────────────────────────────────────
# 5. Risk manager — örnek hesap
# ─────────────────────────────────────────────────────────────────
print("\n=== 5. Risk manager regression ===")
from risk_manager import RiskManager
old_rm = RiskManager()

# Stop loss
sl_old = old_rm.calculate_stop_loss(100.0, "long", 0.02)
sl_new = risk.calculate_stop_loss(100.0, "long", 0.02)
check("stop_loss eşit", sl_old == sl_new, f"{sl_old} vs {sl_new}")

# Take profit (risk_reward=2.0, stop_pct=0.02)
tp_old = old_rm.calculate_take_profit(100.0, "long", 2.0, 0.02)
tp_new = risk.calculate_take_profit(100.0, "long", 2.0, 0.02)
check("take_profit eşit", tp_old == tp_new, f"{tp_old} vs {tp_new}")

# ATR-based stop (multiplier=None → config'den ATR_MULTIPLIER alır)
atr_sl_old = old_rm.atr_stop_loss(100.0, 2.5, "long")
atr_sl_new = risk.atr_stop_loss(100.0, 2.5, "long")
check("atr_stop_loss eşit", atr_sl_old == atr_sl_new, f"{atr_sl_old} vs {atr_sl_new}")

# ATR-based take profit
atr_tp_old = old_rm.atr_take_profit(100.0, 2.5, "long", 2.0)
atr_tp_new = risk.atr_take_profit(100.0, 2.5, "long", 2.0)
check("atr_take_profit eşit", atr_tp_old == atr_tp_new, f"{atr_tp_old} vs {atr_tp_new}")

# Dynamic position sizing
ps_old = old_rm.dynamic_position_size(
    equity=100000, entry_price=150, stop_loss_price=145, confidence=8, regime="bull",
)
ps_new = risk.dynamic_position_size(
    equity=100000, entry_price=150, stop_loss_price=145, confidence=8, regime="bull",
)
check("dynamic_position_size eşit", ps_old == ps_new, f"qty old={ps_old.get('qty')} new={ps_new.get('qty')}")


# ─────────────────────────────────────────────────────────────────
# 6. Scheduler mode tespit
# ─────────────────────────────────────────────────────────────────
print("\n=== 6. Scheduler mode regression ===")
from scheduler import _detect_scan_mode
old_mode = _detect_scan_mode()
new_mode = sched.detect_scan_mode()
check("detect_scan_mode eşit", old_mode == new_mode, f"{old_mode} vs {new_mode}")


# ─────────────────────────────────────────────────────────────────
# 7. ABC contract — equity adapter'lar BaseX subclass mı?
# ─────────────────────────────────────────────────────────────────
print("\n=== 7. ABC inheritance ===")
check("EquityRiskAdapter is BaseRiskManager", isinstance(risk, BaseRiskManager))
check("EquityBrainAdapter is BaseBrain", isinstance(brain, BaseBrain))
check("EquityRegimeAdapter is BaseRegimeDetector", isinstance(regime, BaseRegimeDetector))
check("EquitySchedulerAdapter is BaseScheduler", isinstance(sched, BaseScheduler))


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

print("\n[OK] V5.8 refactor regression testi yeşil — equity davranışı birebir aynı.")
sys.exit(0)
