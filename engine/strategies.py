"""
Стратегії як чисті функції сигналів.

Кожна стратегія перетворює список барів на список ЦІЛЬОВИХ ПОЗИЦІЙ по барах:
    1.0  = у лонгу на весь капітал,
    0.0  = поза ринком.
(spot, без шортів — як на Binance spot testnet).

Сигнал на барі i розраховується ТІЛЬКИ за даними [0..i] — жодного зазирання в
майбутнє. Це критично: типова причина "бектест бреше" — lookahead bias.

Бектестер і live-раннер потім самі вирішують, КОЛИ і ПО ЯКІЙ ЦІНІ виконати зміну
позиції (на закритті бару vs на відкритті наступного + slippage) — саме там
живе execution gap, тож логіку сигналу і логіку виконання тримаємо нарізно.
"""
from dataclasses import dataclass, field


def _ema(values, period):
    """EMA-серія тієї ж довжини, що й values."""
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi_series(closes, period):
    """RSI по Wilder для кожного бару (None, поки даних замало)."""
    n = len(closes)
    out = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


@dataclass
class Strategy:
    key: str
    name: str
    desc: str
    params: dict
    grid: dict = field(default_factory=dict)   # параметр -> список значень для оптимізації

    def with_params(self, **overrides):
        p = {**self.params, **{k: v for k, v in overrides.items() if v is not None}}
        return type(self)(self.key, self.name, self.desc, p, self.grid)

    def warmup(self) -> int:
        """Скільки початкових барів — "розігрів" (позиція=0, не торгуємо)."""
        return 0

    def target_positions(self, candles) -> list:
        raise NotImplementedError


class EmaCross(Strategy):
    """Трендова: лонг, поки EMA(fast) > EMA(slow), інакше — кеш."""

    def warmup(self):
        return int(self.params["slow"])

    def target_positions(self, candles):
        closes = [c["c"] for c in candles]
        fast = _ema(closes, int(self.params["fast"]))
        slow = _ema(closes, int(self.params["slow"]))
        w = self.warmup()
        pos = []
        for i in range(len(closes)):
            if i < w:
                pos.append(0.0)
            else:
                pos.append(1.0 if fast[i] > slow[i] else 0.0)
        return pos


class RsiReversion(Strategy):
    """
    Контртрендова: купуємо перепроданість (RSI < low), виходимо на RSI > high.
    Між порогами тримаємо попередню позицію (гістерезис).
    """

    def warmup(self):
        return int(self.params["period"]) + 1

    def target_positions(self, candles):
        closes = [c["c"] for c in candles]
        rsi = _rsi_series(closes, int(self.params["period"]))
        low, high = float(self.params["low"]), float(self.params["high"])
        pos, cur = [], 0.0
        for i in range(len(closes)):
            r = rsi[i]
            if r is not None:
                if r < low:
                    cur = 1.0
                elif r > high:
                    cur = 0.0
            pos.append(cur)
        return pos


# Реєстр двох "перспективних на бектесті" стратегій — точка входу для бота.
STRATEGIES = {
    "ema_cross": EmaCross(
        key="ema_cross",
        name="EMA Cross (trend)",
        desc="Лонг, поки швидка EMA вище повільної; вихід — навпаки.",
        params={"fast": 12, "slow": 48},
        grid={"fast": [8, 12, 21, 34], "slow": [48, 55, 89, 144]},
    ),
    "rsi_rev": RsiReversion(
        key="rsi_rev",
        name="RSI Reversion (mean-revert)",
        desc="Купити перепроданість (RSI<low), вийти на RSI>high.",
        params={"period": 14, "low": 30, "high": 70},
        grid={"period": [7, 14, 21], "low": [20, 25, 30], "high": [65, 70, 75]},
    ),
}


def get_strategy(key: str) -> Strategy:
    s = STRATEGIES.get(key)
    if not s:
        raise KeyError(f"Невідома стратегія: {key}. Доступні: {', '.join(STRATEGIES)}")
    return s
