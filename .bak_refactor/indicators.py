"""
БЛОК 4 (частина) — технічні індикатори та конфлюенс-скоринг.

Працює на ряді цін close (за замовчуванням 30-денний годинний ряд, який бот
уже отримує для ризику). Індикатори:
- EMA(fast/slow) кросовер
- MACD(12,26,9) — лінія, сигнал, гістограма
- Bollinger Bands(20,2) — положення ціни в каналі
- RSI(14) — з analysis.py
- Бичача/ведмежа дивергенція RSI vs ціна

confluence() зважує сигнали в єдиний бал від -100 (сильний шорт) до
+100 (сильний лонг) і дає вердикт простою мовою.
"""

from analysis import rsi as _rsi


def ema_series(prices, period):
    """Повний ряд EMA (а не лише останнє значення)."""
    if not prices:
        return []
    k = 2.0 / (period + 1)
    out = [prices[0]]
    for p in prices[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def macd(prices, fast=12, slow=26, signal=9):
    """Повертає (macd_line, signal_line, histogram) — останні значення."""
    if len(prices) < slow + signal:
        return 0.0, 0.0, 0.0
    ef = ema_series(prices, fast)
    es = ema_series(prices, slow)
    macd_line = [a - b for a, b in zip(ef, es)]
    sig = ema_series(macd_line, signal)
    return macd_line[-1], sig[-1], macd_line[-1] - sig[-1]


def bollinger(prices, period=20, mult=2.0):
    """Повертає (lower, mid, upper, %B) для останньої точки."""
    if len(prices) < period:
        return (0.0, 0.0, 0.0, 0.5)
    window = prices[-period:]
    mid = sum(window) / period
    var = sum((p - mid) ** 2 for p in window) / period
    sd = var ** 0.5
    upper, lower = mid + mult * sd, mid - mult * sd
    last = prices[-1]
    pct_b = (last - lower) / (upper - lower) if upper != lower else 0.5
    return lower, mid, upper, pct_b


def ema_cross(prices, fast=12, slow=48):
    """+1 золотий хрест (fast>slow), -1 мертвий хрест, 0 невизначено."""
    if len(prices) < slow + 2:
        return 0
    ef, es = ema_series(prices, fast), ema_series(prices, slow)
    return 1 if ef[-1] > es[-1] else -1


def rsi_divergence(prices, lookback=40, period=14):
    """
    Груба детекція дивергенції на останньому вікні:
    +1 — бичача (ціна нижчий мінімум, RSI вищий мінімум),
    -1 — ведмежа (ціна вищий максимум, RSI нижчий максимум), 0 — немає.
    """
    if len(prices) < lookback + period:
        return 0
    window = prices[-lookback:]
    half = lookback // 2
    p1, p2 = window[:half], window[half:]
    r1 = _rsi(prices[-lookback:-half] or prices[:half])
    r2 = _rsi(prices[-half:])
    # ведмежа: ціна робить вищий максимум, RSI — нижчий
    if max(p2) > max(p1) and r2 < r1:
        return -1
    # бичача: ціна робить нижчий мінімум, RSI — вищий
    if min(p2) < min(p1) and r2 > r1:
        return 1
    return 0


def confluence(prices):
    """
    Зводить індикатори в єдиний бал -100..+100 та вердикт.
    Повертає dict: score, verdict, signals[(name, value, bias)].
    """
    signals = []
    score = 0.0

    cross = ema_cross(prices)
    if cross > 0:
        score += 25; signals.append(("EMA 12/48", "золотий хрест", "лонг"))
    elif cross < 0:
        score -= 25; signals.append(("EMA 12/48", "мертвий хрест", "шорт"))

    m, s, hist = macd(prices)
    if hist > 0:
        score += 20; signals.append(("MACD", f"гіст {hist:+.4g}", "лонг"))
    elif hist < 0:
        score -= 20; signals.append(("MACD", f"гіст {hist:+.4g}", "шорт"))

    r = _rsi(prices)
    if r < 30:
        score += 20; signals.append(("RSI", f"{r:.0f} перепродано", "лонг"))
    elif r > 70:
        score -= 20; signals.append(("RSI", f"{r:.0f} перекуплено", "шорт"))
    elif r < 45:
        score += 7; signals.append(("RSI", f"{r:.0f}", "слабко лонг"))
    elif r > 55:
        score -= 7; signals.append(("RSI", f"{r:.0f}", "слабко шорт"))
    else:
        signals.append(("RSI", f"{r:.0f}", "нейтрально"))

    lower, mid, upper, pct_b = bollinger(prices)
    if pct_b <= 0.05:
        score += 18; signals.append(("Bollinger %B", f"{pct_b:.2f} біля низу", "лонг"))
    elif pct_b >= 0.95:
        score -= 18; signals.append(("Bollinger %B", f"{pct_b:.2f} біля верху", "шорт"))
    else:
        signals.append(("Bollinger %B", f"{pct_b:.2f}", "в каналі"))

    div = rsi_divergence(prices)
    if div > 0:
        score += 17; signals.append(("Дивергенція RSI", "бичача", "лонг"))
    elif div < 0:
        score -= 17; signals.append(("Дивергенція RSI", "ведмежа", "шорт"))

    score = max(-100.0, min(100.0, score))
    if score >= 40:
        verdict = "СИЛЬНИЙ ЛОНГ"
    elif score >= 15:
        verdict = "ЛОНГ"
    elif score <= -40:
        verdict = "СИЛЬНИЙ ШОРТ"
    elif score <= -15:
        verdict = "ШОРТ"
    else:
        verdict = "НЕЙТРАЛЬНО"

    return {"score": round(score, 1), "verdict": verdict, "signals": signals}
