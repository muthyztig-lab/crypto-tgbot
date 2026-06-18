"""
Функція 2: вибір ЛОНГ або ШОРТ + рівні Stop Loss / Take Profit.

Бот зважує кілька сигналів і обирає найвигідніший напрямок:
- Тренд (EMA 12 vs EMA 48): за трендом вигідніше відкриватися
- RSI: перепроданість (<30) -> аргумент за лонг, перекупленість (>70) -> за шорт
- Momentum (зміна за останні 24 точки): підтверджує напрямок
- Зміна за 24 години: короткострокове підтвердження

Додатково рахує рекомендовані рівні на основі ATR:
- Stop Loss  = ціна -/+ 1.5 * ATR
- Take Profit = ціна +/- 2.5 * ATR
- Risk/Reward = 1 : 1.67

Повертає напрямок, впевненість у %, пояснення факторів та рівні.
"""

from analysis import atr_from_prices, rsi, trend_direction

SL_ATR_MULT = 1.5   # множник ATR для Stop Loss
TP_ATR_MULT = 2.5   # множник ATR для Take Profit


def long_short_signal(prices, change_24h_pct=0.0, current_price=None):
    """Головна функція сигналу. prices — 30-денний годинний ряд."""
    score = 0.0  # >0 -> LONG, <0 -> SHORT
    reasons = []

    # ------------------------------------------------------------------
    # 1. Тренд — найвагоміший фактор
    # ------------------------------------------------------------------
    tr = trend_direction(prices)
    if tr == 1:
        score += 2.0
        reasons.append(("Тренд (EMA12/EMA48)", "висхідний", "+ лонг"))
    elif tr == -1:
        score -= 2.0
        reasons.append(("Тренд (EMA12/EMA48)", "низхідний", "+ шорт"))
    else:
        reasons.append(("Тренд (EMA12/EMA48)", "флет", "нейтрально"))

    # ------------------------------------------------------------------
    # 2. RSI — контртрендовий фактор
    # ------------------------------------------------------------------
    r = rsi(prices)
    if r < 30:
        score += 1.5
        reasons.append(("RSI", f"{r:.0f} (перепроданість)", "+ лонг"))
    elif r > 70:
        score -= 1.5
        reasons.append(("RSI", f"{r:.0f} (перекупленість)", "+ шорт"))
    elif r < 45:
        score += 0.5
        reasons.append(("RSI", f"{r:.0f}", "слабко за лонг"))
    elif r > 55:
        score -= 0.5
        reasons.append(("RSI", f"{r:.0f}", "слабко за шорт"))
    else:
        reasons.append(("RSI", f"{r:.0f}", "нейтрально"))

    # ------------------------------------------------------------------
    # 3. Momentum за останні 24 точки
    # ------------------------------------------------------------------
    if len(prices) > 24 and prices[-25] != 0:
        mom = (prices[-1] - prices[-25]) / prices[-25]
        if mom > 0.01:
            score += 1.0
            reasons.append(("Momentum 24т", f"{mom * 100:+.1f}%", "+ лонг"))
        elif mom < -0.01:
            score -= 1.0
            reasons.append(("Momentum 24т", f"{mom * 100:+.1f}%", "+ шорт"))
        else:
            reasons.append(("Momentum 24т", f"{mom * 100:+.1f}%", "нейтрально"))

    # ------------------------------------------------------------------
    # 4. Зміна за 24 години
    # ------------------------------------------------------------------
    if change_24h_pct > 1.0:
        score += 0.5
        reasons.append(("Зміна 24г", f"{change_24h_pct:+.1f}%", "+ лонг"))
    elif change_24h_pct < -1.0:
        score -= 0.5
        reasons.append(("Зміна 24г", f"{change_24h_pct:+.1f}%", "+ шорт"))
    else:
        reasons.append(("Зміна 24г", f"{change_24h_pct:+.1f}%", "нейтрально"))

    # ------------------------------------------------------------------
    # Підсумок: напрямок та впевненість
    # ------------------------------------------------------------------
    direction = "LONG" if score >= 0 else "SHORT"
    confidence = min(round(abs(score) / 5.0 * 100), 100)
    if confidence < 20:
        direction = "НЕЙТРАЛЬНО"

    # ------------------------------------------------------------------
    # Рівні Stop Loss / Take Profit на основі ATR
    # ------------------------------------------------------------------
    price = current_price if current_price else (prices[-1] if prices else 0.0)
    atr = atr_from_prices(prices)
    stop_loss = take_profit = None
    if price and atr and direction in ("LONG", "SHORT"):
        if direction == "LONG":
            stop_loss = price - SL_ATR_MULT * atr
            take_profit = price + TP_ATR_MULT * atr
        else:
            stop_loss = price + SL_ATR_MULT * atr
            take_profit = price - TP_ATR_MULT * atr

    return {
        "direction": direction,
        "confidence": confidence,
        "score": round(score, 2),
        "reasons": reasons,
        "entry": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": round(TP_ATR_MULT / SL_ATR_MULT, 2),
        "atr": atr,
    }
