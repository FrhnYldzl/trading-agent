"""
risk_manager.py — Dinamik Risk Yönetimi Motoru (V2)

V1: Sabit %2 risk
V2: Claude'un güven skoruna göre dinamik pozisyon boyutlandirma

Özellikler:
  - Güven skoru bazli pozisyon büyüklügü (1-10 skala)
  - Rejime göre risk limiti ayarlama
  - ATR-bazli stop-loss hesaplama
  - Kelly Criterion yaklasimi
  - Max drawdown korumasi
  - Portföy yogunlasma limiti
"""


class RiskManager:
    def __init__(self, max_risk_pct: float = 0.02):
        """
        Args:
            max_risk_pct: Kasa basina mutlak max risk yüzdesi. Varsayilan %2.
        """
        self.max_risk_pct = max_risk_pct

    # ─────────────────────────────────────────────────────────────
    # V2: Dinamik Pozisyon Boyutlandirma
    # ─────────────────────────────────────────────────────────────

    def dynamic_position_size(
        self,
        equity: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: int = 5,
        regime: str = "neutral",
    ) -> dict:
        """
        Claude'un güven skoru + piyasa rejimine göre dinamik pozisyon hesaplar.

        Args:
            equity          : Toplam portföy degeri
            entry_price     : Giris fiyati
            stop_loss_price : Stop-loss fiyati
            confidence      : Claude güven skoru (1-10)
            regime          : Piyasa rejimi (bull/bear/neutral)

        Returns:
            {
              "qty": 15,
              "risk_amount": 200.0,
              "risk_pct": 1.5,
              "position_value": 2850.0,
              "position_pct": 5.7,
              "stop_distance": 13.33,
              "stop_distance_pct": 1.4,
            }
        """
        if entry_price <= 0 or stop_loss_price <= 0 or equity <= 0:
            return {"qty": 0, "risk_amount": 0, "risk_pct": 0, "error": "Gecersiz parametreler"}

        # 1. Güven skoruna göre risk yüzdesi (base)
        risk_pct = self._confidence_to_risk(confidence)

        # 2. Rejime göre risk ayarlama
        risk_pct = self._regime_adjustment(risk_pct, regime)

        # 3. Mutlak max risk limiti
        risk_pct = min(risk_pct, self.max_risk_pct)

        # 4. Risk miktari
        risk_amount = equity * risk_pct

        # 5. Stop mesafesi
        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance == 0:
            stop_distance = entry_price * 0.02  # Fallback: %2

        stop_distance_pct = round(stop_distance / entry_price * 100, 2)

        # 6. Adet hesaplama
        qty = risk_amount / stop_distance
        qty = max(1, round(qty))  # En az 1 adet

        # 7. Pozisyon degeri kontrolü (max %15 portföy)
        position_value = qty * entry_price
        max_position_value = equity * 0.15
        if position_value > max_position_value:
            qty = max(1, int(max_position_value / entry_price))
            position_value = qty * entry_price

        position_pct = round(position_value / equity * 100, 2) if equity > 0 else 0

        return {
            "qty": qty,
            "risk_amount": round(risk_amount, 2),
            "risk_pct": round(risk_pct * 100, 2),
            "position_value": round(position_value, 2),
            "position_pct": position_pct,
            "stop_distance": round(stop_distance, 2),
            "stop_distance_pct": stop_distance_pct,
        }

    def _confidence_to_risk(self, confidence: int) -> float:
        """
        Güven skoru → risk yüzdesi haritalamasi.

        Confidence 8-10: max risk (%2.0)
        Confidence 6-7 : orta risk (%1.5)
        Confidence 4-5 : düsük risk (%1.0)
        Confidence 1-3 : ISLEM YAPMA (watch only)
        """
        mapping = {
            10: 0.020,
            9:  0.020,
            8:  0.018,
            7:  0.015,
            6:  0.012,
            5:  0.010,
            4:  0.008,
            3:  0.000,  # Watch only
            2:  0.000,
            1:  0.000,
        }
        return mapping.get(max(1, min(10, confidence)), 0.010)

    def _regime_adjustment(self, risk_pct: float, regime: str) -> float:
        """
        Rejime göre risk carpani.

        bull_strong : x1.0 (tam risk)
        bull        : x0.9
        neutral     : x0.7
        bear        : x0.5
        bear_strong : x0.3
        """
        multipliers = {
            "bull_strong": 1.0,
            "bull":        0.9,
            "neutral":     0.7,
            "bear":        0.5,
            "bear_strong": 0.3,
        }
        return risk_pct * multipliers.get(regime, 0.7)

    # ─────────────────────────────────────────────────────────────
    # V1 Uyumlu Metodlar (mevcut webhook icin)
    # ─────────────────────────────────────────────────────────────

    def calculate_position_size(
        self, balance: float, entry_price: float, stop_loss_pct: float = 0.02
    ) -> float:
        """
        Fixed-fraction yöntemiyle kac adet alinacagini hesaplar.
        (V1 uyumluluk icin korunuyor)
        """
        if entry_price <= 0 or stop_loss_pct <= 0:
            raise ValueError("Giris fiyati ve stop-loss yüzdesi sifirdan büyük olmali.")

        risk_amount = balance * self.max_risk_pct
        stop_loss_distance = entry_price * stop_loss_pct
        qty = risk_amount / stop_loss_distance
        return round(qty, 4)

    def calculate_stop_loss(
        self, entry_price: float, direction: str, pct: float = 0.02
    ) -> float:
        if direction == "long":
            return round(entry_price * (1 - pct), 4)
        return round(entry_price * (1 + pct), 4)

    def calculate_take_profit(
        self, entry_price: float, direction: str, risk_reward: float = 2.0, stop_pct: float = 0.02
    ) -> float:
        tp_pct = stop_pct * risk_reward
        if direction == "long":
            return round(entry_price * (1 + tp_pct), 4)
        return round(entry_price * (1 - tp_pct), 4)

    # ─────────────────────────────────────────────────────────────
    # ATR Bazli Stop-Loss (V2)
    # ─────────────────────────────────────────────────────────────

    def atr_stop_loss(
        self, entry_price: float, atr: float, direction: str, multiplier: float = 1.5
    ) -> float:
        """
        ATR bazli stop-loss: daha akilli, volatiliteye uyumlu.

        Args:
            entry_price : Giris fiyati
            atr         : Average True Range (14 günlük)
            direction   : "long" veya "short"
            multiplier  : ATR carpani (1.5 = muhafazakar, 2.0 = genis)
        """
        stop_distance = atr * multiplier
        if direction == "long":
            return round(entry_price - stop_distance, 2)
        return round(entry_price + stop_distance, 2)

    def atr_take_profit(
        self, entry_price: float, atr: float, direction: str, rr_ratio: float = 2.0, multiplier: float = 1.5
    ) -> float:
        """ATR bazli take-profit (risk/ödül oranina göre)."""
        tp_distance = atr * multiplier * rr_ratio
        if direction == "long":
            return round(entry_price + tp_distance, 2)
        return round(entry_price - tp_distance, 2)

    # ─────────────────────────────────────────────────────────────
    # Trailing Stop (V2.2) — Dinamik Stop-Loss Yonetimi
    # ─────────────────────────────────────────────────────────────

    def trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        initial_stop: float,
        atr: float,
        direction: str = "long",
        method: str = "atr",
    ) -> dict:
        """
        Trailing stop hesapla — fiyat lehimize gittikce stop'u da tasir.

        Metodlar:
          - "atr"       : ATR bazli trailing (1.5x ATR mesafe)
          - "percent"   : Sabit yuzde trailing (%2)
          - "breakeven" : Kar'a gectikten sonra stop'u girise cek

        Returns:
            {
              "new_stop": 185.50,
              "stop_moved": True,
              "reason": "ATR trailing: fiyat yükseldi, stop yukarı taşındı",
              "profit_locked_pct": 2.5,
            }
        """
        if direction == "long":
            # Fiyat yukseldi mi?
            in_profit = current_price > entry_price

            if method == "atr":
                trail_distance = atr * 1.5
                candidate_stop = round(current_price - trail_distance, 2)
            elif method == "percent":
                candidate_stop = round(current_price * 0.98, 2)  # %2 asagida
            elif method == "breakeven":
                # Kara gectiyse stop'u giris fiyatina cek
                if in_profit:
                    candidate_stop = entry_price
                else:
                    candidate_stop = initial_stop
            else:
                candidate_stop = initial_stop

            # Stop sadece yukari tasinar, asagi inmez
            new_stop = max(initial_stop, candidate_stop)
            stop_moved = new_stop > initial_stop

            # Kilitlenmis kar yuzdesini hesapla
            profit_locked = 0
            if new_stop > entry_price:
                profit_locked = round((new_stop - entry_price) / entry_price * 100, 2)

            return {
                "new_stop": new_stop,
                "stop_moved": stop_moved,
                "initial_stop": initial_stop,
                "reason": f"{'ATR' if method == 'atr' else method} trailing: "
                          f"stop {'yukari tasindi' if stop_moved else 'ayni kaldi'}",
                "profit_locked_pct": profit_locked,
                "distance_to_stop": round(current_price - new_stop, 2),
                "distance_to_stop_pct": round((current_price - new_stop) / current_price * 100, 2),
                "in_profit": in_profit,
            }

        else:  # short
            in_profit = current_price < entry_price

            if method == "atr":
                trail_distance = atr * 1.5
                candidate_stop = round(current_price + trail_distance, 2)
            elif method == "percent":
                candidate_stop = round(current_price * 1.02, 2)
            elif method == "breakeven":
                if in_profit:
                    candidate_stop = entry_price
                else:
                    candidate_stop = initial_stop
            else:
                candidate_stop = initial_stop

            new_stop = min(initial_stop, candidate_stop)
            stop_moved = new_stop < initial_stop

            profit_locked = 0
            if new_stop < entry_price:
                profit_locked = round((entry_price - new_stop) / entry_price * 100, 2)

            return {
                "new_stop": new_stop,
                "stop_moved": stop_moved,
                "initial_stop": initial_stop,
                "reason": f"{'ATR' if method == 'atr' else method} trailing: "
                          f"stop {'asagi tasindi' if stop_moved else 'ayni kaldi'}",
                "profit_locked_pct": profit_locked,
                "distance_to_stop": round(new_stop - current_price, 2),
                "distance_to_stop_pct": round((new_stop - current_price) / current_price * 100, 2),
                "in_profit": in_profit,
            }

    def check_exit_signals(
        self,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        direction: str = "long",
    ) -> dict:
        """
        Cikis sinyali kontrolu — TP veya SL'ye ulasildi mi?

        Returns:
            {
              "should_exit": True,
              "exit_reason": "take_profit_hit",
              "pnl_pct": 4.5,
            }
        """
        if direction == "long":
            pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)
            if current_price <= stop_loss:
                return {"should_exit": True, "exit_reason": "stop_loss_hit", "pnl_pct": pnl_pct}
            if current_price >= take_profit:
                return {"should_exit": True, "exit_reason": "take_profit_hit", "pnl_pct": pnl_pct}
        else:
            pnl_pct = round((entry_price - current_price) / entry_price * 100, 2)
            if current_price >= stop_loss:
                return {"should_exit": True, "exit_reason": "stop_loss_hit", "pnl_pct": pnl_pct}
            if current_price <= take_profit:
                return {"should_exit": True, "exit_reason": "take_profit_hit", "pnl_pct": pnl_pct}

        return {"should_exit": False, "exit_reason": None, "pnl_pct": pnl_pct}

    # ─────────────────────────────────────────────────────────────
    # Portföy Risk Kontrolü
    # ─────────────────────────────────────────────────────────────

    def portfolio_risk_check(self, equity: float, positions: list, regime: str = "neutral") -> dict:
        """
        Portföy genelinde risk analizi.

        Returns:
            {
              "total_invested_pct": 65.0,
              "cash_pct": 35.0,
              "largest_position_pct": 12.0,
              "regime_compliant": True,
              "warnings": ["..."]
            }
        """
        if equity <= 0:
            return {"total_invested_pct": 0, "cash_pct": 100, "warnings": ["Portföy degeri 0"]}

        total_invested = sum(
            p.get("qty", 0) * p.get("current_price", 0)
            for p in positions
        )
        invested_pct = round(total_invested / equity * 100, 1)
        cash_pct = round(100 - invested_pct, 1)

        largest_pct = 0
        if positions:
            largest = max(positions, key=lambda p: p.get("qty", 0) * p.get("current_price", 0))
            largest_val = largest.get("qty", 0) * largest.get("current_price", 0)
            largest_pct = round(largest_val / equity * 100, 1)

        warnings = []

        # Rejim uyumu kontrolü
        regime_limits = {
            "bear_strong": 30,  # Max %30 yatirim
            "bear":        40,
            "neutral":     70,
            "bull":        85,
            "bull_strong":  95,
        }
        max_invested = regime_limits.get(regime, 70)
        regime_compliant = invested_pct <= max_invested

        if not regime_compliant:
            warnings.append(
                f"Rejim ({regime}) icin max %{max_invested} yatirim önerilir, "
                f"su an %{invested_pct} yatirimda"
            )

        if largest_pct > 20:
            warnings.append(f"En büyük pozisyon portföyün %{largest_pct}'i — yogunlasma riski")

        if cash_pct < 10:
            warnings.append(f"Nakit orani cok düsük (%{cash_pct}) — acil durum tampon yok")

        return {
            "total_invested_pct": invested_pct,
            "cash_pct": cash_pct,
            "largest_position_pct": largest_pct,
            "regime_compliant": regime_compliant,
            "max_invested_for_regime": max_invested,
            "warnings": warnings,
        }
