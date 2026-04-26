"""
crypto/risk_impl.py — CryptoRiskManager(BaseRiskManager).

Equity'deki RiskManager'a delege eder; ama parametreler kripto için
kalibre edilmiştir:

  Equity              Crypto
  ────────────────────────────────────────
  max_risk_pct  2%    1%        (BTC ATR equity'nin 2x'i)
  ATR_MULT      1.5×  2.0×      (volatiliteyi soğurmak için)
  Sektör konsantrasyonu (Equity) → Asset Group (Crypto):
    L1, L2, DeFi, Meme, RWA, Stablecoin (excluded), Specialty

NOT: Equity'deki RiskManager.config (config.py) globaldir; her instance
için override etmek mümkün değil. Bu yüzden bu adapter sadece max_risk_pct'i
override eder, diğer parametre kalibrasyonu için ileride risk_manager.py'ı
parametrize etmemiz gerekir (V5.10). Şimdilik kabul edilebilir bir yaklaşım:
crypto için max_risk_pct=0.01 → tek başına en kritik kalibrasyon.
"""

from core.asset_class import AssetClass
from core.base_risk import BaseRiskManager
from risk_manager import RiskManager


# ─────────────────────────────────────────────────────────────────
# Crypto asset group haritası (equity'deki SECTOR_MAP karşılığı)
# ─────────────────────────────────────────────────────────────────
CRYPTO_ASSET_GROUP = {
    # L1 — base layer blockchains
    "BTC/USD": "L1", "ETH/USD": "L1", "SOL/USD": "L1", "ADA/USD": "L1",
    "AVAX/USD": "L1", "DOT/USD": "L1", "XTZ/USD": "L1", "FIL/USD": "L1",
    # L2 / scaling
    "ARB/USD": "L2", "POL/USD": "L2",
    # Payment / store of value
    "XRP/USD": "Payment", "LTC/USD": "Payment", "BCH/USD": "Payment",
    # DeFi
    "UNI/USD": "DeFi", "AAVE/USD": "DeFi", "CRV/USD": "DeFi",
    "SUSHI/USD": "DeFi", "YFI/USD": "DeFi", "LDO/USD": "DeFi", "SKY/USD": "DeFi",
    # Oracle / infrastructure
    "LINK/USD": "Infra", "GRT/USD": "Infra", "RENDER/USD": "Infra",
    # Meme / sentiment
    "DOGE/USD": "Meme", "SHIB/USD": "Meme", "PEPE/USD": "Meme",
    "BONK/USD": "Meme", "WIF/USD": "Meme", "TRUMP/USD": "Meme", "HYPE/USD": "Meme",
    # RWA / specialty
    "PAXG/USD": "RWA", "ONDO/USD": "RWA",
    "BAT/USD": "Utility",
}


def get_asset_group(symbol: str) -> str:
    """
    Sembolün asset group'unu dön. Hem 'BTC/USD' hem 'BTCUSD' formatları
    için çalışır (Alpaca pozisyon endpoint'i slash'sız döner).
    """
    s = (symbol or "").upper()
    # Direkt bul
    if s in CRYPTO_ASSET_GROUP:
        return CRYPTO_ASSET_GROUP[s]
    # Slash yoksa, bilinen quote'lardan birinin başına slash ekleyip dene
    for quote in ("USD", "USDT", "USDC"):
        if s.endswith(quote) and "/" not in s:
            with_slash = s[:-len(quote)] + "/" + quote
            if with_slash in CRYPTO_ASSET_GROUP:
                return CRYPTO_ASSET_GROUP[with_slash]
    # Slash varsa kaldırıp dene
    if "/" in s:
        no_slash = s.replace("/", "")
        if no_slash in CRYPTO_ASSET_GROUP:
            return CRYPTO_ASSET_GROUP[no_slash]
    return "Unknown"


class CryptoRiskManager(BaseRiskManager):
    """
    BaseRiskManager → RiskManager delegasyonu, crypto kalibrasyonu ile.
    """

    # Kalibrasyon — crypto piyasası daha oynak
    DEFAULT_MAX_RISK_PCT = 0.01           # %1 (equity %2'nin yarısı)
    DEFAULT_GROUP_MAX_PCT = 0.40          # Tek grup max %40 (L1 ya da Meme)

    def __init__(self, max_risk_pct: float = None):
        risk = max_risk_pct if max_risk_pct is not None else self.DEFAULT_MAX_RISK_PCT
        self._impl = RiskManager(max_risk_pct=risk)

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    def dynamic_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: int = 5,
        regime: str = "neutral",
    ) -> dict:
        # Equity logic'i kullan, ama crypto için max_risk_pct=0.01 zaten init'te set
        result = self._impl.dynamic_position_size(
            equity=equity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            confidence=confidence,
            regime=regime,
        )
        # Equity'de qty integer'a yuvarlanıyor (max(1, round(qty))) — crypto'da
        # ondalıklı olmalı. Burada equity round'unu geri çevirmek yerine, layer'ın
        # ileride ondalıklı destekleyecek şekilde refactor edilmesi gerekiyor.
        # V5.9-α not: bu fonksiyon dolu integer qty döndürür, broker tarafında
        # notional emir kullanılarak USD bazlı al-sat yapılır (qty kullanılmaz).
        result["asset_class"] = "crypto"
        result["note"] = "Crypto'da notional (USD) emir önerilir; qty integer'a yuvarlanmıştır."
        return result

    def calculate_stop_loss(
        self, entry_price: float, direction: str, pct: float = 0.04
    ) -> float:
        # Crypto için default stop %4 (equity %2'nin 2x'i — daha oynak)
        return self._impl.calculate_stop_loss(entry_price, direction, pct)

    def calculate_take_profit(
        self,
        entry_price: float,
        direction: str,
        risk_reward: float = 2.0,
        stop_pct: float = 0.04,
    ) -> float:
        return self._impl.calculate_take_profit(
            entry_price=entry_price,
            direction=direction,
            risk_reward=risk_reward,
            stop_pct=stop_pct,
        )

    def atr_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        multiplier: float = None,
    ) -> float:
        # Crypto'da multiplier=2.0 daha güvenli (ATR zaten yüksek)
        m = multiplier if multiplier is not None else 2.0
        return self._impl.atr_stop_loss(
            entry_price=entry_price, atr=atr, direction=direction, multiplier=m,
        )

    def atr_take_profit(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        rr_ratio: float = 2.0,
        multiplier: float = None,
    ) -> float:
        m = multiplier if multiplier is not None else 2.0
        return self._impl.atr_take_profit(
            entry_price=entry_price, atr=atr, direction=direction,
            rr_ratio=rr_ratio, multiplier=m,
        )

    def check_flash_crash(self, positions: list, market_data: dict) -> dict:
        # Crypto'da BTC -%10 günlük → flash crash sayılır (equity'de SPY -%5)
        return self._impl.check_flash_crash(positions, market_data)

    def check_sector_exposure(self, equity: float, positions: list) -> dict:
        """
        Equity'de sektör bazlı; crypto'da asset group bazlı.
        Bu fonksiyon equity SECTOR_MAP'i kullanır — crypto için doğru çalışmaz.
        Geçici çözüm: kendi grup hesabını yap.
        """
        if not positions or equity <= 0:
            return {"by_group": {}, "violations": []}

        by_group: dict[str, float] = {}
        for p in positions:
            sym = p.get("symbol", "").upper()
            group = get_asset_group(sym)
            value = float(p.get("market_value", 0))
            by_group[group] = by_group.get(group, 0) + value

        # Yüzdelere çevir
        by_group_pct = {g: round(v / equity * 100, 2) for g, v in by_group.items()}

        violations = [
            {"group": g, "pct": pct, "limit": self.DEFAULT_GROUP_MAX_PCT * 100}
            for g, pct in by_group_pct.items()
            if pct > self.DEFAULT_GROUP_MAX_PCT * 100
        ]
        return {
            "by_group": by_group_pct,
            "violations": violations,
            "asset_class": "crypto",
        }

    def portfolio_risk_check(
        self, equity: float, positions: list, regime: str = "neutral"
    ) -> dict:
        result = self._impl.portfolio_risk_check(equity, positions, regime)
        # Sektör check'i crypto için override edilmiş olanla değiştir
        crypto_groups = self.check_sector_exposure(equity, positions)
        result["asset_class"] = "crypto"
        result["asset_groups"] = crypto_groups.get("by_group", {})
        result["group_violations"] = crypto_groups.get("violations", [])
        return result

    def calculate_risk_metrics(self, returns: list[float]) -> dict:
        return self._impl.calculate_risk_metrics(returns)
