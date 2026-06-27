"""
Подієвий бектестер (bar-by-bar), spot, лонг/кеш, увесь капітал у позиції.

Тут навмисно роз'єднані ДВА джерела похибки, які зазвичай ламають перехід
бектест → реальність:

1. Латентність виконання (EXEC_LATENCY_BARS): сигнал відомий на ЗАКРИТТІ бару,
   але реально ми входимо лише на ВІДКРИТТІ наступного бару. latency=0 — це
   "ідеальний" бектест (вхід по ціні закриття того ж бару, часто бреше).
2. Витрати: комісія (fee_bps) + проковзування (slippage_bps).

Один і той самий код використовується для:
  • ідеального бектесту (latency=0, fee=0, slip=0) — верхня межа,
  • реалістичного бектесту (latency=1, реальні fee/slip),
  • відтворення live-прогону на тих самих барах (для reconcile).
"""
from dataclasses import dataclass, field

from engine import metrics
from exchange.binance import BARS_PER_YEAR


@dataclass
class BacktestResult:
    equity: list = field(default_factory=list)        # крива капіталу по барах (mark-to-close)
    trades: list = field(default_factory=list)        # завершені угоди
    fills: list = field(default_factory=list)         # окремі виконання (buy/sell)
    summary: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    exposure_pct: float = 0.0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0


def backtest(candles, positions, *, fee_bps, slippage_bps, latency_bars,
             start_equity, interval="1h"):
    n = len(candles)
    fee = fee_bps / 10_000
    slip = slippage_bps / 10_000
    cash, units, cur = start_equity, 0.0, 0.0
    equity, trades, fills = [], [], []
    fees_paid = slippage_paid = 0.0
    bars_in_market = 0
    entry = None

    # Заплановані виконання: бар_виконання -> цільова позиція (0/1).
    pending = {}
    prev = 0.0
    for i in range(n):
        if positions[i] != prev:
            eb = i + latency_bars
            if eb < n:
                pending[eb] = positions[i]
            prev = positions[i]

    for i in range(n):
        bar = candles[i]
        if i in pending:
            target = pending[i]
            ref = bar["o"] if latency_bars > 0 else bar["c"]
            if target > cur:  # BUY: входимо в лонг усім кешем
                exec_price = ref * (1 + slip)
                slippage_paid += cash * slip
                fee_cost = cash * fee
                fees_paid += fee_cost
                units = (cash - fee_cost) / exec_price
                equity_before = cash
                cash = 0.0
                entry = {"bar": i, "t": bar["t"], "price": exec_price,
                         "equity_before": equity_before}
                fills.append({"bar": i, "t": bar["t"], "side": "BUY",
                              "ref_price": ref, "exec_price": exec_price,
                              "fee": fee_cost})
            elif target < cur and units > 0:  # SELL: повний вихід
                exec_price = ref * (1 - slip)
                proceeds = units * exec_price
                slippage_paid += units * ref * slip
                fee_cost = proceeds * fee
                fees_paid += fee_cost
                cash = proceeds - fee_cost
                if entry:
                    pnl_abs = cash - entry["equity_before"]
                    trades.append({
                        "entry_t": entry["t"], "exit_t": bar["t"],
                        "entry_price": entry["price"], "exit_price": exec_price,
                        "bars": i - entry["bar"],
                        "pnl_abs": round(pnl_abs, 4),
                        "pnl_pct": round(pnl_abs / entry["equity_before"] * 100, 3),
                    })
                fills.append({"bar": i, "t": bar["t"], "side": "SELL",
                              "ref_price": ref, "exec_price": exec_price,
                              "fee": fee_cost})
                units, entry = 0.0, None
            cur = target

        if units > 0:
            bars_in_market += 1
        equity.append(cash + units * bar["c"])

    # Віртуально закриваємо відкриту позицію на останньому закритті — щоб
    # статистика угод відображала ВСЮ активність, а не лише закриті угоди.
    if units > 0 and entry:
        last = candles[-1]["c"]
        final = units * last
        trades.append({
            "entry_t": entry["t"], "exit_t": candles[-1]["t"],
            "entry_price": entry["price"], "exit_price": last,
            "bars": (n - 1) - entry["bar"],
            "pnl_abs": round(final - entry["equity_before"], 4),
            "pnl_pct": round((final - entry["equity_before"]) / entry["equity_before"] * 100, 3),
            "open": True,
        })

    bpy = BARS_PER_YEAR.get(interval, 8760)
    summary = metrics.summarize(equity, trades, bpy)
    summary["exposure_pct"] = round(bars_in_market / n * 100, 1) if n else 0.0
    summary["fees_paid"] = round(fees_paid, 2)
    summary["slippage_paid"] = round(slippage_paid, 2)
    summary["bars"] = n

    return BacktestResult(
        equity=equity, trades=trades, fills=fills, summary=summary,
        exposure_pct=summary["exposure_pct"],
        fees_paid=round(fees_paid, 2), slippage_paid=round(slippage_paid, 2),
    )


def run_strategy(strategy, candles, *, fee_bps, slippage_bps, latency_bars,
                 start_equity, interval="1h"):
    """Зручна обгортка: рахує сигнали стратегії й проганяє бектест."""
    positions = strategy.target_positions(candles)
    res = backtest(candles, positions, fee_bps=fee_bps, slippage_bps=slippage_bps,
                   latency_bars=latency_bars, start_equity=start_equity,
                   interval=interval)
    res.params = dict(strategy.params)
    return res


def buy_hold(candles, start_equity, fee_bps=0.0):
    """Бенчмарк Buy & Hold для тих самих барів."""
    if len(candles) < 2 or not candles[0]["c"]:
        return {"total_return_pct": 0.0, "final_equity": start_equity}
    fee = fee_bps / 10_000
    units = (start_equity * (1 - fee)) / candles[0]["c"]
    final = units * candles[-1]["c"]
    return {
        "total_return_pct": round((final / start_equity - 1) * 100, 2),
        "final_equity": round(final, 2),
    }
