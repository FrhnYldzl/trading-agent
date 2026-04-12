"""
equity.py — Alpaca Paper Trading Broker Modulu (V2.2)

V2.2 Guvenlik Sistemi:
  - Order Loop (Stutter) Korumasi: ayni ticker icin 60sn cooldown
  - Piyasa Saati Kontrolu: kapali iken emir engelleme
  - Fiyat Dogrulama: %20+ sapma = emir engelleme
  - PDT Guard: day_trade >= 3 ise yeni pozisyon kilitleme
  - Pre-Market Cleanup: acilistan once stale emirleri iptal
  - Cancel All Orders: tum bekleyen emirleri temizleme
"""

import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

load_dotenv()


class EquityBroker:
    def __init__(self):
        self.client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True,
        )
        # 10 saniye baglanti timeout
        original_request = self.client._session.request
        def request_with_timeout(method, url, **kwargs):
            kwargs.setdefault("timeout", 10)
            return original_request(method, url, **kwargs)
        self.client._session.request = request_with_timeout

        # Order Loop Korumasi
        self._recent_orders: dict[str, float] = {}
        self._order_cooldown = 60

    # ── Ana islem metodu ──────────────────────────────────────────

    def execute(self, action: str, ticker: str, qty: float, price: float) -> dict:
        action = action.lower().strip()
        ticker = ticker.upper().strip()

        # 1. Piyasa saati kontrolu (yeni pozisyonlar icin)
        if action in ("long", "short"):
            market_check = self._check_market_hours()
            if not market_check["open"]:
                return {
                    "status": "rejected",
                    "ticker": ticker,
                    "reason": f"Piyasa kapali. {market_check['message']}",
                    "action_blocked": action,
                }

        # 2. PDT Guard (yeni pozisyonlar icin)
        if action in ("long", "short"):
            pdt_check = self._check_pdt_limit()
            if not pdt_check["allowed"]:
                return {
                    "status": "rejected",
                    "ticker": ticker,
                    "reason": pdt_check["reason"],
                    "action_blocked": action,
                    "pdt_count": pdt_check.get("day_trade_count", 0),
                }

        # 3. Order Loop (Stutter) korumasi
        loop_check = self._check_order_loop(ticker, action)
        if not loop_check["allowed"]:
            return {
                "status": "rejected",
                "ticker": ticker,
                "reason": loop_check["reason"],
                "action_blocked": action,
                "cooldown_remaining": loop_check.get("remaining", 0),
            }

        # 4. Fiyat dogrulama (%20+ sapma kontrolu)
        if price > 0 and action in ("long", "short"):
            price_check = self._validate_price(ticker, price)
            if not price_check["valid"]:
                return {
                    "status": "rejected",
                    "ticker": ticker,
                    "reason": price_check["reason"],
                    "action_blocked": action,
                }

        # 5. Emri gonder
        if action == "long":
            result = self._buy(ticker, qty)
        elif action == "short":
            result = self._sell_short(ticker, qty)
        elif action in ("close_long", "close_short"):
            result = self._close_position(ticker)
        else:
            raise ValueError(f"Bilinmeyen aksiyon: '{action}'")

        # 6. Basarili emri kaydet (loop korumasi icin)
        if result.get("status") not in ("error", "rejected"):
            self._recent_orders[ticker] = time.time()

        return result

    # ── Alim / Satim ──────────────────────────────────────────────

    def _buy(self, ticker: str, qty: float) -> dict:
        req = MarketOrderRequest(
            symbol=ticker,
            qty=max(1, int(qty)),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(req)
        return self._order_to_dict(order)

    def _sell_short(self, ticker: str, qty: float) -> dict:
        req = MarketOrderRequest(
            symbol=ticker,
            qty=max(1, int(qty)),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(req)
        return self._order_to_dict(order)

    def _close_position(self, ticker: str) -> dict:
        try:
            result = self.client.close_position(ticker)
            return {"status": "closed", "ticker": ticker, "detail": str(result)}
        except Exception as e:
            return {"status": "error", "ticker": ticker, "message": str(e)}

    # ── PDT Guard ────────────────────────────────────────────────

    def _check_pdt_limit(self) -> dict:
        """
        Pattern Day Trader korumasi.
        $25K alti hesaplarda rolling 5 gunde max 3 day trade.
        day_trade >= 3 ise yeni pozisyon acmayi engeller (kapatma serbest).
        """
        try:
            account = self.client.get_account()
            equity = float(account.equity)
            day_trade_count = int(account.daytrade_count)

            # $25K ustu hesaplar PDT kuralina tabi degil
            if equity >= 25000:
                return {
                    "allowed": True,
                    "day_trade_count": day_trade_count,
                    "message": "PDT kural: $25K ustu hesap, limit yok.",
                }

            if day_trade_count >= 3:
                return {
                    "allowed": False,
                    "day_trade_count": day_trade_count,
                    "reason": f"PDT KILIDI: {day_trade_count}/3 day trade kullanildi. "
                              f"Yeni pozisyon acmak hesabi kisitlatir! "
                              f"Sadece mevcut pozisyonlari kapatabilirsiniz. "
                              f"Hesap bakiyesi: ${equity:,.2f} (<$25K PDT siniri).",
                }

            remaining = 3 - day_trade_count
            return {
                "allowed": True,
                "day_trade_count": day_trade_count,
                "remaining": remaining,
                "message": f"PDT: {day_trade_count}/3 kullanildi, {remaining} kaldi.",
            }
        except Exception as e:
            # API hatasi — guvenligi tercih et, uyar ama engelleme
            print(f"[PDT Guard] Kontrol hatasi: {e}")
            return {
                "allowed": True,
                "day_trade_count": -1,
                "message": f"PDT kontrol hatasi: {e}. Emre izin verildi.",
            }

    # ── Pre-Market Cleanup ───────────────────────────────────────

    def cancel_all_orders(self) -> dict:
        """
        Tum bekleyen (open/pending) emirleri iptal et.
        Pre-market temizligi icin: eski/stale emirlerin
        acilista tetiklenmesini onler.
        """
        try:
            cancelled = self.client.cancel_orders()
            count = len(cancelled) if cancelled else 0
            print(f"[Cleanup] {count} bekleyen emir iptal edildi.")
            return {
                "status": "ok",
                "cancelled_count": count,
                "message": f"{count} bekleyen emir iptal edildi.",
            }
        except Exception as e:
            print(f"[Cleanup] Emir iptal hatasi: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    def get_pending_orders(self) -> list:
        """Bekleyen emirleri listele."""
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.client.get_orders(req)
            return [
                {
                    "order_id": str(o.id),
                    "ticker": o.symbol,
                    "side": str(o.side),
                    "qty": str(o.qty),
                    "status": str(o.status),
                    "submitted_at": str(o.submitted_at),
                    "type": str(o.type),
                }
                for o in orders
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ── Guvenlik Kontrolleri ─────────────────────────────────────

    def _check_order_loop(self, ticker: str, action: str) -> dict:
        """Ayni ticker icin 60sn cooldown."""
        if action in ("close_long", "close_short"):
            return {"allowed": True}

        now = time.time()
        last_order_time = self._recent_orders.get(ticker, 0)
        elapsed = now - last_order_time

        if elapsed < self._order_cooldown:
            remaining = round(self._order_cooldown - elapsed)
            return {
                "allowed": False,
                "reason": f"Order loop korumasi: {ticker} icin son {int(elapsed)}sn once emir verildi. "
                          f"{remaining}sn beklenmeli (cooldown={self._order_cooldown}sn).",
                "remaining": remaining,
            }

        # Eski kayitlari temizle (5dk'dan eski)
        cutoff = now - 300
        self._recent_orders = {
            k: v for k, v in self._recent_orders.items() if v > cutoff
        }
        return {"allowed": True}

    def _check_market_hours(self) -> dict:
        """Alpaca clock API ile piyasa durumu kontrol."""
        try:
            clock = self.client.get_clock()
            if clock.is_open:
                return {"open": True, "message": "Piyasa acik"}
            else:
                next_open = str(clock.next_open)[:16] if clock.next_open else "?"
                return {
                    "open": False,
                    "message": f"Sonraki acilis: {next_open} UTC. "
                               "Piyasa kapali iken emir gonderilemez.",
                }
        except Exception:
            now = datetime.now(timezone.utc)
            if now.weekday() >= 5:
                return {"open": False, "message": "Hafta sonu — piyasa kapali."}
            hour = now.hour
            if 13 <= hour < 20:
                return {"open": True, "message": "Piyasa tahminen acik (UTC fallback)"}
            return {"open": False, "message": "Piyasa tahminen kapali (UTC fallback)"}

    def _validate_price(self, ticker: str, signal_price: float) -> dict:
        """Sinyal fiyati vs gercek fiyat: %20+ fark = engelle."""
        try:
            pos = None
            try:
                pos = self.client.get_open_position(ticker)
            except Exception:
                pass

            if pos and hasattr(pos, "current_price"):
                current = float(pos.current_price)
                diff_pct = abs(current - signal_price) / current * 100
                if diff_pct > 20:
                    return {
                        "valid": False,
                        "reason": f"FIYAT UYUMSUZLUGU: Sinyal ${signal_price:.2f} vs "
                                  f"gercek ${current:.2f} (fark: %{diff_pct:.0f}). "
                                  f"Emir guvenlik nedeniyle engellendi.",
                    }
            return {"valid": True}
        except Exception:
            return {"valid": True}

    # ── Hesap bilgileri ───────────────────────────────────────────

    def get_balance(self) -> float:
        account = self.client.get_account()
        return float(account.cash)

    def get_account_status(self) -> dict:
        """Detayli hesap durumu — PDT, nakit, pozisyonlar."""
        try:
            account = self.client.get_account()
            return {
                "cash": float(account.cash),
                "equity": float(account.equity),
                "buying_power": float(account.buying_power),
                "portfolio_value": float(account.portfolio_value),
                "daytrade_count": int(account.daytrade_count),
                "pdt_check": "OK" if int(account.daytrade_count) < 3 else "LOCKED",
                "pattern_day_trader": bool(account.pattern_day_trader),
                "trading_blocked": bool(account.trading_blocked),
                "account_blocked": bool(account.account_blocked),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_position(self, ticker: str) -> dict | None:
        try:
            pos = self.client.get_open_position(ticker)
            return {
                "ticker": ticker,
                "qty": float(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "unrealized_pl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    # ── Yardimcilar ───────────────────────────────────────────────

    @staticmethod
    def _order_to_dict(order) -> dict:
        return {
            "order_id": str(order.id),
            "ticker": order.symbol,
            "side": str(order.side),
            "qty": str(order.qty),
            "status": str(order.status),
            "submitted_at": str(order.submitted_at),
        }
