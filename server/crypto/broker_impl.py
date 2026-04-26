"""
crypto/broker_impl.py — CryptoBroker(BaseBroker) implementation.

Equity'deki broker/equity.py'nin kripto karşılığı. Önemli farklar:

  - Aynı Alpaca TradingClient kullanılır (Alpaca tek hesap, asset class
    sembolden belli olur: "BTC/USD" gibi crypto-pair otomatik crypto
    endpoint'ine yönlenir).
  - Ondalıklı qty (notional miktar = USD bazlı emir).
  - PDT kuralı YOK — gün içi al-sat sınırsız.
  - Market saati kontrolü YOK — 24/7.
  - Bracket order desteği SINIRLIDIR (Alpaca crypto bazı türler için
    bracket'i daha sınırlı tutuyor) — bu implementasyon market + limit
    emirler için bracket kullanmaz, ayrı SL/TP emirleri sonradan koyulur.
  - Settlement instant — partial fill nadiren olur.

⚠️ GÜVENLİK: Bu sınıf default olarak `dry_run=True` ile init edilir.
Order placement metotları (`execute`, `emergency_liquidate`, `_buy`, `_sell`)
dry-run modda HİÇBİR EMİR GÖNDERMEZ — sadece "ne göndereceğini" simüle
eder ve dict döner. Gerçek emir için açıkça `dry_run=False` ile
init edilmelidir, V5.9 kapsamında bunu YAPMAYACAĞIZ. Live geçişi ayrı
ve bilinçli bir adımla yapılacak.
"""

import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from core.asset_class import AssetClass
from core.base_broker import BaseBroker

load_dotenv()


class CryptoBroker(BaseBroker):
    """
    BaseBroker implementation — Alpaca crypto endpoints üzerinden.

    init params:
        dry_run: True ise order placement metotları gerçek emir göndermez,
                 simüle edilmiş başarı dict'i döner. Default True (güvenlik).
        paper:   Alpaca paper account mı? Default True. Live için False
                 verilmesi gerekir AMA V5.9'da live'a geçilmeyecek.
    """

    def __init__(self, dry_run: bool = True, paper: bool = None):
        """
        V5.9-ε: Multi-account support.
        Crypto modülü kendi Alpaca hesabını kullanabilir:
          CRYPTO_ALPACA_API_KEY     (set ise crypto-only)
          CRYPTO_ALPACA_SECRET_KEY
          CRYPTO_ALPACA_PAPER       (true/false)
        Set edilmediyse default ALPACA_* key'lerine fallback.
        """
        from alpaca.trading.client import TradingClient
        self.dry_run = dry_run

        # Crypto-specific key'ler set edildi mi?
        api_key = os.getenv("CRYPTO_ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("CRYPTO_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")

        if paper is None:
            paper_env = (os.getenv("CRYPTO_ALPACA_PAPER", "true") or "true").lower()
            paper = paper_env in ("true", "1", "yes")
        self.paper = paper

        # Hangi hesap aktif?
        self.account_label = os.getenv("CRYPTO_ACCOUNT_LABEL") or (
            "Ferhan Crypto Paper" if os.getenv("CRYPTO_ALPACA_API_KEY")
            else "Default (Equity Paper)"
        )
        self.is_dedicated_account = bool(os.getenv("CRYPTO_ALPACA_API_KEY"))

        self.client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
        )
        # Equity broker'daki gibi 10sn timeout
        original_request = self.client._session.request
        def request_with_timeout(method, url, **kwargs):
            kwargs.setdefault("timeout", 10)
            return original_request(method, url, **kwargs)
        self.client._session.request = request_with_timeout

    @property
    def asset_class(self) -> AssetClass:
        return AssetClass.CRYPTO

    # ───────────────────────────────────────────────────────────
    # READ-ONLY metotlar — gerçek API'yı çağırır, side-effect yok
    # ───────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        try:
            acct = self.client.get_account()
            return float(acct.cash)
        except Exception as e:
            print(f"[CryptoBroker] get_balance hatası: {e}")
            return 0.0

    def get_account_status(self) -> dict:
        try:
            acct = self.client.get_account()
            return {
                "cash": float(acct.cash),
                "equity": float(acct.equity),
                "buying_power": float(acct.buying_power),
                "portfolio_value": float(acct.portfolio_value),
                "trading_blocked": acct.trading_blocked,
                "account_blocked": acct.account_blocked,
                "pattern_day_trader": acct.pattern_day_trader,  # crypto için anlamsız ama bilgi
                "currency": acct.currency,
                "status": str(acct.status),
                "asset_class": "crypto",
                "paper": self.paper,
                "dry_run": self.dry_run,
                "account_label": self.account_label,
                "is_dedicated_account": self.is_dedicated_account,
            }
        except Exception as e:
            return {"error": str(e), "asset_class": "crypto",
                    "account_label": getattr(self, "account_label", "?")}

    def get_position(self, ticker: str) -> dict | None:
        """
        ticker: "BTC/USD" gibi (slash format).
        Alpaca pozisyon endpoint'inde sembol genelde slash'sız ("BTCUSD") olabilir;
        her iki formatı da deniyoruz.
        """
        try:
            # Önce slash'lı dene
            try:
                pos = self.client.get_open_position(ticker)
            except Exception:
                # Slash'sız fallback
                pos = self.client.get_open_position(ticker.replace("/", ""))
            return {
                "symbol": pos.symbol,
                "qty": float(pos.qty),
                "side": str(pos.side),
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price) if pos.current_price else None,
                "market_value": float(pos.market_value),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc),
            }
        except Exception:
            return None

    def get_pending_orders(self) -> list:
        """Tüm bekleyen emirler — equity ve crypto karışık döner; filtrelenir."""
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200)
            orders = self.client.get_orders(req)
            crypto_orders = []
            for o in orders:
                # Crypto sembolleri slash'lı veya "BTCUSD" formatında olabilir
                sym = o.symbol or ""
                is_crypto = "/" in sym or any(
                    sym.endswith(q) for q in ("USD", "USDT", "USDC", "BTC", "ETH")
                ) and len(sym) <= 8
                if is_crypto:
                    crypto_orders.append({
                        "id": str(o.id),
                        "symbol": sym,
                        "qty": float(o.qty) if o.qty else None,
                        "notional": float(o.notional) if o.notional else None,
                        "side": str(o.side),
                        "type": str(o.order_type),
                        "status": str(o.status),
                        "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                    })
            return crypto_orders
        except Exception as e:
            return [{"error": str(e)}]

    # ───────────────────────────────────────────────────────────
    # SIDE-EFFECT metotları — dry_run koruması
    # ───────────────────────────────────────────────────────────

    def execute(
        self,
        action: str,
        ticker: str,
        qty: float,
        price: float,
        stop_loss: float = None,
        take_profit: float = None,
        order_type: str = "market",
    ) -> dict:
        """
        Crypto emri gönder. action: "long", "short", "close_long", "close_short".

        ⚠️ Crypto'da SHORT genellikle desteklenmez (Alpaca paper hariç bazı
        durumlarda). Bu impl shorting'i şimdilik reject eder.
        """
        action = action.lower().strip()
        ticker = ticker.upper().strip()

        # Crypto: short genelde yok, perp ayrı API
        if action == "short":
            return {
                "status": "rejected", "ticker": ticker,
                "reason": "Crypto spot'ta short desteklenmiyor (perp ayrı API).",
            }

        if action == "close_short":
            return {
                "status": "rejected", "ticker": ticker,
                "reason": "Açık short olamaz, kapama işlemi geçersiz.",
            }

        # ─── DRY-RUN GUARD ──────────────────────────────────
        if self.dry_run:
            return {
                "status": "dry_run",
                "ticker": ticker,
                "action": action,
                "qty": qty,
                "price": price,
                "order_type": order_type,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "message": "DRY-RUN modunda — gerçek emir gönderilmedi.",
                "would_send": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # ─── V5.10-ζ: GERÇEK ALPACA CRYPTO ORDER ────────────
        # Aksiyon dispatch (long/close_long/reduce destekli; short crypto'da yok)
        if action == "long":
            return self._buy_crypto(ticker, qty, price, stop_loss, take_profit, order_type)
        elif action == "close_long":
            return self._close_crypto_position(ticker)
        elif action == "reduce":
            return self._reduce_crypto_position(ticker, qty)
        else:
            return {
                "status": "error",
                "ticker": ticker,
                "reason": f"Bilinmeyen action: {action}",
            }

    # ───────────────────────────────────────────────────────────
    # V5.10-ζ: Gerçek Alpaca crypto order metotları
    # ───────────────────────────────────────────────────────────

    def _buy_crypto(
        self, ticker: str, qty: float, price: float,
        stop_loss: float = None, take_profit: float = None,
        order_type: str = "market",
    ) -> dict:
        """
        Crypto buy emri — Alpaca paper.

        Tasarım:
          - **Notional (USD-bazlı) emir** kullanırız — fractional crypto için en
            temiz yöntem (qty 0.0064 BTC yerine "$500 worth of BTC" diyoruz).
          - Alpaca crypto **bracket order desteklemez** — stop_loss ve
            take_profit emir olarak gönderilmez. Bunun yerine journal'a
            HEDEF olarak kaydedilir, V5.10-η.4 polling ile takip edilir
            ve hit olunca market emirle kapatılır.
          - time_in_force: GTC (Good Till Cancelled) — crypto için standart.
        """
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        # Notional hesabı — qty * price = USD değer
        if qty <= 0 or price <= 0:
            return {
                "status": "error", "ticker": ticker,
                "reason": f"Geçersiz qty/price: qty={qty}, price={price}",
            }
        notional = round(qty * price, 2)
        if notional < 1.0:
            return {
                "status": "error", "ticker": ticker,
                "reason": f"Notional çok küçük: ${notional} (Alpaca min ~$1)",
            }

        try:
            if order_type == "limit" and price > 0:
                req = LimitOrderRequest(
                    symbol=ticker,
                    qty=round(qty, 8),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                    limit_price=round(price, 4),
                )
            else:
                # Default: market with notional
                req = MarketOrderRequest(
                    symbol=ticker,
                    notional=notional,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                )
            order = self.client.submit_order(req)
            result = self._order_to_dict(order)
            # Stop/TP HEDEF olarak işaretle (emir yok, sadece ekle)
            result["notional_usd"] = notional
            result["stop_loss_target"] = stop_loss
            result["take_profit_target"] = take_profit
            result["bracket_note"] = (
                "Alpaca crypto bracket desteklemez — stop/TP scheduler "
                "polling ile takip edilir (V5.10-η.4)."
            )
            return result
        except Exception as e:
            return {
                "status": "error", "ticker": ticker,
                "reason": f"Alpaca order failed: {e}",
            }

    def _close_crypto_position(self, ticker: str) -> dict:
        """Tüm pozisyonu market sell ile kapat."""
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        # Pozisyonu bul
        pos = None
        for sym_form in (ticker, ticker.replace("/", "")):
            try:
                pos = self.client.get_open_position(sym_form)
                break
            except Exception:
                continue
        if not pos:
            return {
                "status": "error", "ticker": ticker,
                "reason": "Açık pozisyon bulunamadı",
            }

        side = OrderSide.SELL if str(pos.side).lower() in ("long", "positionside.long") else OrderSide.BUY
        try:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=float(pos.qty),
                side=side,
                time_in_force=TimeInForce.GTC,
            )
            order = self.client.submit_order(req)
            result = self._order_to_dict(order)
            result["closed_qty"] = float(pos.qty)
            result["closed_avg_entry"] = float(pos.avg_entry_price)
            return result
        except Exception as e:
            return {
                "status": "error", "ticker": ticker,
                "reason": f"close failed: {e}",
            }

    def _reduce_crypto_position(self, ticker: str, qty: float) -> dict:
        """Pozisyonu kısmen kapat (verilen qty kadar sat)."""
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        pos = self.get_position(ticker)
        if not pos:
            return {"status": "error", "ticker": ticker, "reason": "Pozisyon yok"}

        sell_qty = min(qty, pos.get("qty", 0))
        if sell_qty <= 0:
            return {"status": "error", "ticker": ticker, "reason": f"Geçersiz reduce qty: {sell_qty}"}

        try:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=round(sell_qty, 8),
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
            )
            order = self.client.submit_order(req)
            result = self._order_to_dict(order)
            result["reduced_qty"] = sell_qty
            return result
        except Exception as e:
            return {"status": "error", "ticker": ticker, "reason": f"reduce failed: {e}"}

    @staticmethod
    def _order_to_dict(order) -> dict:
        """Alpaca Order objesini dict'e çevir."""
        return {
            "status": str(order.status).split(".")[-1].lower() if order.status else "submitted",
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": float(order.qty) if order.qty else None,
            "notional": float(order.notional) if order.notional else None,
            "side": str(order.side).split(".")[-1].lower() if order.side else None,
            "order_type": str(order.order_type).split(".")[-1].lower() if order.order_type else None,
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_qty": float(order.filled_qty) if order.filled_qty else None,
        }

    def cancel_all_orders(self) -> dict:
        """Bekleyen tüm crypto emirlerini iptal et."""
        if self.dry_run:
            pending = self.get_pending_orders()
            return {
                "status": "dry_run",
                "would_cancel": len(pending),
                "message": "DRY-RUN — gerçekte iptal edilmedi.",
            }
        try:
            cancels = self.client.cancel_orders()
            return {"cancelled": len(cancels) if cancels else 0}
        except Exception as e:
            return {"error": str(e)}

    def emergency_liquidate(self) -> dict:
        """Tüm crypto pozisyonlarını piyasada kapa."""
        if self.dry_run:
            try:
                positions = self.client.get_all_positions()
                crypto_positions = [
                    p for p in positions
                    if p.asset_class and "crypto" in str(p.asset_class).lower()
                ]
                return {
                    "status": "dry_run",
                    "would_liquidate": len(crypto_positions),
                    "symbols": [p.symbol for p in crypto_positions],
                    "message": "DRY-RUN — gerçekte tasfiye edilmedi.",
                }
            except Exception as e:
                return {"error": str(e)}
        return {
            "status": "error",
            "reason": "Live crypto liquidate V5.9'da implement edilmedi (güvenlik).",
        }
