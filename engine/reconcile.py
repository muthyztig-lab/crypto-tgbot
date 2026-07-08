import time
import json
import asyncio

from core import db
from core import settings
from engine import backtester
from engine.strategies import get_strategy
from exchange import binance

_BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
           "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _total_return(equity):
    if len(equity) < 2 or not equity[0]:
        return 0.0
    return (equity[-1] / equity[0] - 1) * 100


async def _fetch(symbol, tf, limit, testnet=False):
    return await asyncio.to_thread(binance.fetch_klines, symbol, tf, limit,
                                   None, testnet)


async def reconcile(run_id: int) -> dict:
    run = await db.get_run(run_id)
    if not run:
        return {"error": "Прогін не знайдено."}

    eq_points = await db.list_equity(run_id)
    fills = await db.list_fills(run_id)
    if len(eq_points) < 2:
        return {"error": "Замало live-даних. Дай прогону попрацювати "
                         "хоча б кілька барів і спробуй знову."}

    symbol, tf = run["symbol"], run["timeframe"]
    strat = get_strategy(run["strategy"]).with_params(**json.loads(run["params_json"]))
    start_equity = run["start_equity"]
    bar_ms = _BAR_MS.get(tf, 3_600_000)

    use_testnet = run["mode"] == "live" and settings.BINANCE_TESTNET
    candles_all = await _fetch(symbol, tf, 1000, use_testnet)
    warmup_ms = (strat.warmup() + 5) * bar_ms
    lo = run["start_ts"] * 1000 - warmup_ms
    hi = (run["stop_ts"] or int(time.time())) * 1000
    candles = [c for c in candles_all if lo <= c["t"] <= hi]
    if len(candles) < strat.warmup() + 5:
        return {"error": "Замало барів для відтворення бектесту на цьому періоді."}

    kw = dict(start_equity=start_equity, interval=tf)
    ideal = backtester.run_strategy(strat, candles, fee_bps=0, slippage_bps=0,
                                    latency_bars=0, **kw)
    timing = backtester.run_strategy(strat, candles, fee_bps=0, slippage_bps=0,
                                     latency_bars=1, **kw)
    costs = backtester.run_strategy(strat, candles, fee_bps=run["fee_bps"],
                                    slippage_bps=run["slippage_bps"],
                                    latency_bars=1, **kw)

    r_ideal = ideal.summary["total_return_pct"]
    r_timing = timing.summary["total_return_pct"]
    r_costs = costs.summary["total_return_pct"]
    r_live = round(_total_return([p["equity"] for p in eq_points]), 2)

    timing_cost = round(r_ideal - r_timing, 2)
    cost_cost = round(r_timing - r_costs, 2)
    residual = round(r_costs - r_live, 2)
    total_gap = round(r_ideal - r_live, 2)

    live_fees = round(sum(f["fee"] for f in fills), 4)
    live_slip = round(sum(abs(f["exec_price"] - f["ref_price"]) * f["qty"]
                          for f in fills), 4)

    return {
        "run": run,
        "strategy_name": strat.name,
        "params": dict(strat.params),
        "bars": len(candles),
        "live_fills": len(fills),
        "returns": {
            "ideal": r_ideal,
            "with_timing": r_timing,
            "with_costs": r_costs,
            "live": r_live,
            "buy_hold": backtester.buy_hold(candles, start_equity)["total_return_pct"],
        },
        "gap": {
            "total": total_gap,
            "timing_cost": timing_cost,
            "cost_cost": cost_cost,
            "residual": residual,
        },
        "live_fees_usdt": live_fees,
        "live_slippage_usdt": live_slip,
        "verdict": _verdict(total_gap, timing_cost, cost_cost, residual, r_live),
    }


def _verdict(total, timing, cost, residual, live):
    lines = [f"Live у {'плюсі' if live > 0 else 'мінусі'}: {live:+.2f}%."]
    biggest = max(("запізнення виконання", timing),
                  ("комісії+проковзування", cost),
                  ("незмодельований residual", residual),
                  key=lambda x: abs(x[1]))
    lines.append(f"Найбільший внесок у розрив — {biggest[0]} ({biggest[1]:+.2f}%).")
    if abs(residual) > abs(timing) + abs(cost):
        lines.append("⚠️ Residual домінує: причина НЕ в моделі витрат, а в "
                     "інфраструктурі (пропущені бари, гранулярність полінгу, "
                     "часткові виконання). Це місце, де 'бектест бреше' найсильніше.")
    elif abs(total) < 1.0:
        lines.append("✅ Розрив малий — live добре відтворює бектест на цьому періоді.")
    return " ".join(lines)
