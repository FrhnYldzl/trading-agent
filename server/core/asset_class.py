"""
asset_class.py — Asset class enumeration.

Trading-agent'ın desteklediği varlık sınıflarını tanımlar.
Şu an sadece EQUITY canlıda; CRYPTO ve OPTIONS V5.9+ için iskelet.
"""

from enum import Enum


class AssetClass(str, Enum):
    """Desteklenen varlık sınıfları."""
    EQUITY = "equity"
    CRYPTO = "crypto"
    OPTIONS = "options"

    @property
    def is_24_7(self) -> bool:
        """24/7 piyasası mı?"""
        return self == AssetClass.CRYPTO

    @property
    def supports_pdt(self) -> bool:
        """PDT (Pattern Day Trader) kuralı geçerli mi?"""
        return self == AssetClass.EQUITY

    @property
    def fractional_default(self) -> bool:
        """Varsayılan olarak ondalıklı pozisyon destekler mi?"""
        return self == AssetClass.CRYPTO
