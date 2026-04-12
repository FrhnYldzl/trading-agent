"""
equity.py — Alpaca Paper Trading Broker Modulu (V3)

V3 Guvenlik + Emir Sistemi:
  - Order Loop (Stutter) Korumasi: ayni ticker icin 60sn cooldown
  - Piyasa Saati Kontrolu: kapali iken emir engelleme
  - Fiyat Dogrulama: %20+ sapma = emir engelleme
  - PDT Guard: day_trade >= 3 ise yeni pozisyon kilitleme
  - Bracket Orders: SL + TP broker seviyesinde (OCO)
  - Limit Order destegi
  - Flash crash entegrasyonu
"""

import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest,
    StopLossRequest, TakeProfitRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus

from config import ORDER_COOLDOWN_SEC, BRACKET_ENABLED

load_dotenv()


class EquityBroker:
    def __init__(self):
        self.client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=True,
        )
        original_request = self.client._session.request
        def request_with_timeout(method, url, **kwargs):
            kwargs.setdefault("timeout", 10)
            return original_request(method, url, **kwargs)
        self.client._session.request = request_with_timeout

        self._recent_orders: dict[str, float] = {}
        self._order_cooldown = ORDER_COOLDOWN_SEC

    # ── Ana islem metodu ──────────────────────────────────────────

    def execute(
        self, action: str, ticker: str, qty: float, price: float,
        stop_loss: float = None, take_profit: float = None,
        order_type: str = "market",
    ) -> dict:
        action = action.lower().strip()
        ticker = ticker.upper().strip()

        # 1. Piyasa saati kontrolu
        if action in ("long", "short"):
            market_check = self._check_market_hours()
            if not market_check["open"]:
                return {"status": "rejected", "ticker": ticker, "reason": f"Piyasa kapali. {market_check['message']}", "action_blocked": action}

        # 2. PDT Guard
        if action in ("long", "short"):
            pdt_check = self._check_pdt_limit()
            if not pdt_check["allowed"]:
                return {"status": "rejected", "ticker": ticker, "reason": pdt_check["reason"], "action_blocked": action, "pdt_count": pdt_check.get("day_trade_count", 0)}

        # 3. Order Loop korumasi
        loop_check = self._check_order_loop(ticker, action)
        if not loop_check["allowed"]:
            return {"status": "rejected", "ticker": ticker, "reason": loop_check["reason"], "action_blocked": action, "cooldown_remaining": loop_check.get("remaining", 0)}

        # 4. Fiyat dogrulama
        if price > 0 and action in ("long", "short"):
            price_check = self._validate_price(ticker, price)
            if not price_check["valid"]:
                return {"status": "rejected", "ticker": ticker, "reason": price_check["reason"], "action_blocked": action}

        # 5. Emri gonder
        if action == "long":
            result = self._buy(ticker, qty, price, stop_loss, take_profit, order_type)
        elif action == "short":
            result = self._sell_short(ticker, qty, price, stop_loss, take_profit, order_type)
        elif action in ("close_long", "close_short"):
            result = self._close_position(ticker)
        else:
            raise ValueError(f"Bilinmeyen aksiyon: '{action}'")

        # 6. Basarili emri kaydet
        if result.get("status") not in ("error", "rejected"):
            self._recent_orders[ticker] = time.time()

        return result

    # ── V3: Bracket Order (SL + TP) ──────────────────────────────

    def _buy(self, ticker: str, qty: float, price: float = 0,
             stop_loss: float = None, take_profit: float = None,
             order_type: str = "market") -> dict:
        qty = max(1, int(qty))

        # Bracket order: SL + TP broker seviyesinde
        if BRACKET_ENABLED and stop_loss and take_profit:
            try:
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
                    take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)),
                )
                order = self.client.submit_order(req)
                result = self._order_to_dict(order)
                result["order_class"] = "bracket"
                result["stop_loss"] = round(stop_loss, 2)
                result["take_profit"] = round(take_profit, 2)
                return result
            except Exception as e:
                # Bracket basarısız olursa basit market order'a düş
                print(f"[Broker] Bracket order hatasi, market order'a dönülüyor: {e}")

        # Limit order
        if order_type == "limit" and price > 0:
            req = LimitOrderRequest(
                symbol=ticker,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                limit_price=round(price, 2),
            )
            order = self.client.submit_order(req)
            result = self._order_to_dict(order)
            result["order_type"] = "limit"
            return result

        # Standard market order
        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(req)
        return self._order_to_dict(order)

    def _sell_short(self, ticker: str, qty: float, price: float = 0,
                    stop_loss: float = None, take_profit: float = None,
                    order_type: str = "market") -> dict:
        qty = max(1, int(qty))

        # Bracket order for short
        if BRACKET_ENABLED and stop_loss and take_profit:
            try:
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
                    take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)),
                )
                order = self.client.submit_order(req)
                result = self._order_to_dict(order)
                result["order_class"] = "bracket"
                result["stop_loss"] = round(stop_loss, 2)
                result["take_profit"] = round(take_profit, 2)
                return result
            except Exception as e:
                print(f"[Broker] Short bracket hatasi, market order'a dönülüyor: {e}")

        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
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
        try:
            account = self.client.get_account()
            equity = float(account.equity)
            day_trade_count = int(account.daytrade_count)

            if equity >= 25000:
                return {"allowed": True, "day_trade_count": day_trade_count, "message": "PDT: $25K ustu, limit yok."}

            if day_trade_count >= 3:
                return {
                    "allowed": False, "day_trade_count": day_trade_count,
                    "reason": f"PDT KILIDI: {day_trade_count}/3 day trade kullanildi. Yeni pozisyon acilamaz! Hesap: ${equity:,.2f} (<$25K).",
                }

            return {"allowed": True, "day_trade_count": day_trade_count, "remaining": 3 - day_trade_count}
        except Exception as e:
            print(f"[PDT Guard] Kontrol hatasi: {e}")
            return {"allowed": True, "day_trade_count": -1, "message": f"PDT kontrol hatasi: {e}"}

    # ── Pre-Market Cleanup ───────────────────────────────────────

    def cancel_all_orders(self) -> dict:
        try:
            cancelled = self.client.cancel_orders()
            count = len(cancelled) if cancelled else 0
            print(f"[Cleanup] {count} bekleyen emir iptal edildi.")
            return {"status": "ok", "cancelled_count": count, "message": f"{count} emir iptal edildi."}
        except Exception as e:
            print(f"[Cleanup] Emir iptal hatasi: {e}")
            return {"status": "error", "message": str(e)}

    def get_pending_orders(self) -> list:
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.client.get_orders(req)
            return [
                {
                    "order_id": str(o.id), "ticker": o.symbol, "side": str(o.side),
                    "qty": str(o.qty), "status": str(o.status), "type": str(o.type),
                    "submitted_at": str(o.submitted_at),
                }
                for o in orders
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ── Guvenlik Kontrolleri ─────────────────────────────────────

    def _check_order_loop(self, ticker: str, action: str) -> dict:
        if action in ("close_long", "close_short"):
            return {"allowed": True}
        now = time.time()
        last = self._recent_orders.get(ticker, 0)
        elapsed = now - last
        if elapsed < self._order_cooldown:
            remaining = round(self._order_cooldown - elapsed)
            return {"allowed": False, "reason": f"Order loop: {ticker} icin {remaining}sn beklenmeli.", "remaining": remaining}
        cutoff = now - 300
        self._recent_orders = {k: v for k, v in self._recent_orders.items() if v > cutoff}
        return {"allowed": True}

    def _check_market_hours(self) -> dict:
        try:
            clock = self.client.get_clock()
            if clock.is_open:
                return {"open": True, "message": "Piyasa acik"}
            next_open = str(clock.next_open)[:16] if clock.next_open else "?"
            return {"open": False, "message": f"Sonraki acilis: {next_open} UTC"}
        except Exception:
            now = datetime.now(timezone.utc)
            if now.weekday() >= 5:
                return {"open": False, "message": "Hafta sonu"}
            if 13 <= now.hour < 20:
                return {"open": True, "message": "Piyasa tahminen acik (UTC fallback)"}
            return {"open": False, "message": "Piyasa tahminen kapali (UTC fallback)"}

    def _validate_price(self, ticker: str, signal_price: float) -> dict:
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
                    return {"valid": False, "reason": f"FIYAT UYUMSUZLUGU: Sinyal ${signal_price:.2f} vs gercek ${current:.2f} (fark: %{diff_pct:.0f})"}
            return {"valid": True}
        except Exception:
            return {"valid": True}

    # ── V3: Flash Crash — Tum pozisyonlari kapat ────────────────

    def emergency_liquidate(self) -> dict:
        """Flash crash tetiklendiginde tum pozisyonlari kapat."""
        try:
            positions = self.client.get_all_positions()
            closed = []
            for pos in positions:
                try:
                    self.client.close_position(pos.symbol)
                    closed.append(pos.symbol)
                except Exception as e:
                    closed.append(f"{pos.symbol} (HATA: {e})")
            self.client.cancel_orders()
            return {"status": "liquidated", "closed": closed, "count": len(closed)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Hesap bilgileri ───────────────────────────────────────────

    def get_balance(self) -> float:
        account = self.client.get_account()
        return float(account.cash)

    def get_account_status(self) -> dict:
        try:
            account = self.client.get_account()
            return {
                "cash": float(account.cash), "equity": float(account.equity),
                "buying_power": float(account.buying_power), "portfolio_value": float(account.portfolio_value),
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
                "ticker": ticker, "qty": float(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "unrealized_pl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    @staticmethod
    def _order_to_dict(order) -> dict:
        return {
            "order_id": str(order.id), "ticker": order.symbol,
            "side": str(order.side), "qty": str(order.qty),
            "status": str(order.status), "submitted_at": str(order.submitted_at),
        }
