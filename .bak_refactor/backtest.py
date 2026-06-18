"""
БЛОК 4 (частина) — простий бектестинг стратегій + трекінг точності.

На вхід — ряд цін close (timestamp, price). Стратегії:
- ema_cross: лонг коли EMA fast перетинає EMA slow вгору, вихід — вниз
- rsi: купити при RSI<30, продати при RSI>70

Рахуємо: к-сть угод, win-rate, сумарну дохідність стратегії, max drawdown
по equity та порівняння з buy&hold. Це чесний, прозорий бектест без
«заглядання в майбутнє» (рішення на барі i, виконання на ціні бару i).
"""

from indicators import ema_series
from analysis import rsi as _rsi, max_drawdown


def _equity_stats(returns):
    """Зі списку дохідностей угод рахує підсумок."""
    if not returns:
        return {"trades": 0, "win_rate": 0.0, "total_return_pct": 0.0,
                "avg_trade_pct": 0.0, "max_dd_pct": 0.0}
    wins = sum(1 for r in returns if r > 0)
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    total = (equity[-1] - 1) * 100
    return {
        "trades": len(returns),
        "win_rate": round(wins / len(returns) * 100, 1),
        "total_return_pct": round(total, 2),
        "avg_trade_pct": round(sum(returns) / len(returns) * 100, 2),
        "max_dd_pct": round(max_drawdown(equity) * 100, 2),
    }


def backtest_ema_cross(prices, fast=12, slow=48):
    ef, es = ema_series(prices, fast), ema_series(prices, slow)
    returns, in_pos, entry = [], False, 0.0
    for i in range(slow, len(prices)):
        up = ef[i] > es[i]
        if up and not in_pos:
            in_pos, entry = True, prices[i]
        elif not up and in_pos:
            returns.append((prices[i] - entry) / entry)
            in_pos = False
    if in_pos:  # закриваємо відкриту позицію по останній ціні
        returns.append((prices[-1] - entry) / entry)
    return _equity_stats(returns)


def backtest_rsi(prices, low=30, high=70, period=14):
    returns, in_pos, entry = [], False, 0.0
    for i in range(period + 1, len(prices)):
        r = _rsi(prices[: i + 1])
        if r < low and not in_pos:
            in_pos, entry = True, prices[i]
        elif r > high and in_pos:
            returns.append((prices[i] - entry) / entry)
            in_pos = False
    if in_pos:
        returns.append((prices[-1] - entry) / entry)
    return _equity_stats(returns)


def buy_hold(prices):
    if len(prices) < 2 or not prices[0]:
        return 0.0
    return round((prices[-1] - prices[0]) / prices[0] * 100, 2)


def run(prices):
    """Запускає всі стратегії й повертає зведення для картки."""
    return {
        "ema_cross": backtest_ema_cross(prices),
        "rsi": backtest_rsi(prices),
        "buy_hold_pct": buy_hold(prices),
        "bars": len(prices),
    }
