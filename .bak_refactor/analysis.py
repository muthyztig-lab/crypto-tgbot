"""
Аналіз ринку та оцінка ризиків обраної криптовалюти.

Метрики:
- Волатильність (annualized, на основі годинних доходностей)
- RSI(14)
- Максимальна просадка (max drawdown) за період
- Тренд (EMA fast vs EMA slow)
- ATR — середній істинний діапазон (для рівнів Stop Loss / Take Profit)
- Рівні підтримки та опору видимого періоду графіка
- Підсумковий ризик-бал 0..100 та категорія ризику

Важливо: ризик-бал та індикатори завжди рахуються на 30-денних годинних
даних (стабільна база), а графік малюється за обраним таймфреймом.
"""

import math
from datetime import datetime


# ===========================================================================
# Базові обчислення
# ===========================================================================

def _returns(prices):
    """Прості доходності між сусідніми точками ціни."""
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1]
    ]


def volatility_annualized(prices, periods_per_year=24 * 365):
    """Річна волатильність на основі годинних доходностей."""
    rs = _returns(prices)
    if len(rs) < 2:
        return 0.0
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    return math.sqrt(var) * math.sqrt(periods_per_year)


def rsi(prices, period=14):
    """Relative Strength Index (Wilder). 0..100."""
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def max_drawdown(prices):
    """Максимальна просадка від пікової ціни за період (0..1)."""
    if not prices:
        return 0.0
    peak = prices[0]
    mdd = 0.0
    for p in prices:
        peak = max(peak, p)
        if peak:
            mdd = max(mdd, (peak - p) / peak)
    return mdd


def ema(prices, period):
    """Експоненціальна ковзна середня."""
    if not prices:
        return 0.0
    k = 2.0 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e


def trend_direction(prices, fast=12, slow=48):
    """+1 — висхідний тренд, -1 — низхідний, 0 — флет."""
    if len(prices) < slow:
        return 0
    f, s = ema(prices, fast), ema(prices, slow)
    if s == 0:
        return 0
    diff = (f - s) / s
    if diff > 0.002:
        return 1
    if diff < -0.002:
        return -1
    return 0


def atr_from_prices(prices, period=14):
    """
    Спрощений ATR на основі цінового ряду (без OHLC):
    середнє абсолютне коливання між сусідніми точками за останні N точок.
    Використовується для розрахунку рівнів Stop Loss / Take Profit.
    """
    if len(prices) < 2:
        return 0.0
    moves = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    tail = moves[-period * 4:] if len(moves) > period * 4 else moves
    return sum(tail) / len(tail) * math.sqrt(period)


def support_resistance(prices):
    """
    Рівні підтримки та опору видимого періоду:
    підтримка — мінімум, опір — максимум останнього вікна.
    Повертає (support, resistance).
    """
    if not prices:
        return 0.0, 0.0
    return min(prices), max(prices)


# ===========================================================================
# Ризик-бал
# ===========================================================================

def risk_score(prices, market_cap=None):
    """
    Ризик-бал 0..100 (вище = ризикованіше).
    Складники:
      волатильність  — до 40 балів (150%+ річної = максимум)
      просадка       — до 30 балів (30%+ за період = максимум)
      RSI-екстремуми — до 15 балів (перегрів або перепроданість)
      капіталізація  — до 15 балів (менша монета = більший ризик)
    """
    vol = volatility_annualized(prices)
    mdd = max_drawdown(prices)
    r = rsi(prices)

    vol_score = min(vol / 1.5, 1.0) * 40
    mdd_score = min(mdd / 0.30, 1.0) * 30
    rsi_score = (abs(r - 50.0) / 50.0) * 15

    cap_score = 15.0
    if market_cap:
        if market_cap > 100e9:
            cap_score = 2.0
        elif market_cap > 10e9:
            cap_score = 5.0
        elif market_cap > 1e9:
            cap_score = 9.0

    total = vol_score + mdd_score + rsi_score + cap_score
    return min(round(total, 1), 100.0)


def risk_category(score):
    """Категорія ризику за балом."""
    if score < 30:
        return "НИЗЬКИЙ"
    if score < 55:
        return "ПОМІРНИЙ"
    if score < 75:
        return "ВИСОКИЙ"
    return "ДУЖЕ ВИСОКИЙ"


def updated_at() -> str:
    """Час оновлення у форматі календаря Windows, з точністю до секунди."""
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


# ===========================================================================
# Повний аналіз
# ===========================================================================

def full_analysis(info: dict, chart_history: list, risk_history: list = None,
                  tf_label: str = "30 днів") -> dict:
    """
    Повний аналіз монети.

    info          — ринкова інформація (get_market_info)
    chart_history — історія для графіка за обраним таймфреймом
    risk_history  — 30-денна годинна історія для індикаторів
                    (якщо None — використовується chart_history)
    tf_label      — підпис таймфрейму для картки
    """
    chart_prices = [p[1] for p in chart_history]
    risk_prices = [p[1] for p in (risk_history or chart_history)]

    score = risk_score(risk_prices, info.get("market_cap"))
    support, resistance = support_resistance(chart_prices)

    return {
        "info": info,
        "prices": chart_prices,
        "timestamps": [p[0] for p in chart_history],
        "risk_prices": risk_prices,
        "tf_label": tf_label,
        "volatility_pct": round(volatility_annualized(risk_prices) * 100, 1),
        "rsi": round(rsi(risk_prices), 1),
        "max_drawdown_pct": round(max_drawdown(risk_prices) * 100, 1),
        "trend": trend_direction(risk_prices),
        "atr": atr_from_prices(risk_prices),
        "support": support,
        "resistance": resistance,
        "risk_score": score,
        "risk_category": risk_category(score),
        "updated_at": updated_at(),
    }
