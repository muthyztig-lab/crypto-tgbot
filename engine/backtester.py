from dataclasses import dataclass, field

from engine import metrics
from exchange.binance import BARS_PER_YEAR


@dataclass
class BacktestResult:
    equity: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    fills: list = field(default_factory=list)
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

    pending = {}
    prev = 0.0
    for i in range(n):
        if positions[i] != prev:
            exec_bar = i + latency_bars
            if exec_bar < n:
                pending[exec_bar] = positions[i]
            prev = positions[i]

    for i in range(n):
        bar = candles[i]
        if i in pending:
            target = pending[i]
            ref = bar["o"] if latency_bars > 0 else bar["c"]
            if target > cur:
                exec_price = ref * (1 + slip)
                slippage_paid += cash * slip
                fee_cost = cash * fee
                fees_paid += fee_cost
                units = (cash - fee_cost) / exec_price
                entry = {"bar": i, "t": bar["t"], "price": exec_price,
                         "equity_before": cash}
                cash = 0.0
                fills.append({"bar": i, "t": bar["t"], "side": "BUY",
                              "ref_price": ref, "exec_price": exec_price,
                              "fee": fee_cost})
            elif target < cur and units > 0:
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

    summary = metrics.summarize(equity, trades, BARS_PER_YEAR.get(interval, 8760))
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
    positions = strategy.target_positions(candles)
    res = backtest(candles, positions, fee_bps=fee_bps, slippage_bps=slippage_bps,
                   latency_bars=latency_bars, start_equity=start_equity,
                   interval=interval)
    res.params = dict(strategy.params)
    return res


def buy_hold(candles, start_equity, fee_bps=0.0):
    if len(candles) < 2 or not candles[0]["c"]:
        return {"total_return_pct": 0.0, "final_equity": start_equity}
    fee = fee_bps / 10_000
    units = (start_equity * (1 - fee)) / candles[0]["c"]
    final = units * candles[-1]["c"]
    return {
        "total_return_pct": round((final / start_equity - 1) * 100, 2),
        "final_equity": round(final, 2),
    }
