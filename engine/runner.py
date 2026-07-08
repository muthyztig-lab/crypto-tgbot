import time
import json
import asyncio
import logging

from core import db
from core import settings
from engine import broker as broker_mod
from engine.strategies import get_strategy
from exchange import binance

log = logging.getLogger(__name__)

_RUNS: dict[int, dict] = {}
_notify = None


def set_notifier(fn):
    global _notify
    _notify = fn


async def _say(run_id, text):
    if _notify:
        try:
            await _notify(run_id, text)
        except Exception:
            log.exception("notify failed")


def _state_from_fills(fills, start_equity):
    cash, units = start_equity, 0.0
    for f in fills:
        if f["side"] == "BUY":
            cash -= f["qty"] * f["exec_price"] + f["fee"]
            units += f["qty"]
        else:
            cash += f["qty"] * f["exec_price"] - f["fee"]
            units -= f["qty"]
    last_pos = 1.0 if units > 1e-9 else 0.0
    return cash, max(units, 0.0), last_pos


async def _run_loop(run_id: int):
    run = await db.get_run(run_id)
    if not run:
        return
    symbol, tf = run["symbol"], run["timeframe"]
    strat = get_strategy(run["strategy"]).with_params(**json.loads(run["params_json"]))
    broker = broker_mod.make_broker(run["mode"], run["fee_bps"], run["slippage_bps"])

    fills = await db.list_fills(run_id)
    cash, units, last_pos = _state_from_fills(fills, run["start_equity"])
    last_bar_ts = fills[-1]["bar_ts"] if fills else 0
    warmup_limit = max(strat.warmup() + 10, 200)
    use_testnet = run["mode"] == "live" and settings.BINANCE_TESTNET

    await _say(run_id, f"▶️ Запущено #{run_id}: {strat.name} на {symbol} {tf} "
                       f"[{broker.mode}], капітал {run['start_equity']:.0f} USDT.")

    while not _RUNS.get(run_id, {}).get("stop"):
        try:
            candles = await asyncio.to_thread(
                binance.fetch_klines, symbol, tf, warmup_limit, None, use_testnet)
            closed = candles[:-1] if len(candles) > 1 else candles
            price = candles[-1]["c"]
            newest = closed[-1]

            if newest["t"] != last_bar_ts:
                last_bar_ts = newest["t"]
                target = strat.target_positions(closed)[-1]

                if target != last_pos:
                    if target > last_pos:
                        fill = broker.buy(symbol, cash, price)
                        cash -= fill.qty * fill.exec_price + fill.fee
                        units += fill.qty
                    else:
                        fill = broker.sell(symbol, units, price)
                        cash += fill.qty * fill.exec_price - fill.fee
                        units = 0.0
                    last_pos = target
                    await db.add_fill(run_id, int(time.time()), newest["t"], fill.side,
                                      fill.qty, fill.ref_price, fill.exec_price,
                                      fill.fee, fill.slippage_bps)
                    await db.set_run_pos(run_id, last_pos)
                    eq = cash + units * price
                    await _say(run_id,
                               f"#{run_id} {fill.side} {symbol} @ {fill.exec_price:.4f} "
                               f"(сигнал {fill.ref_price:.4f}, slip {fill.slippage_bps:.1f}bps, "
                               f"fee {fill.fee:.4f}) | equity {eq:.2f}")

            await db.add_equity_point(run_id, int(time.time()),
                                      cash + units * price, last_pos, price)

        except binance.ExchangeError as e:
            log.warning("run %s: %s", run_id, e)
        except Exception:
            log.exception("run %s loop error", run_id)

        await asyncio.sleep(settings.POLL_SECONDS)

    await db.stop_run(run_id)
    await _say(run_id, f"⏹ Зупинено #{run_id}.")
    _RUNS.pop(run_id, None)


async def start_run(*, user_id, symbol, timeframe, strategy_key, params,
                    mode, fee_bps, slippage_bps, start_equity) -> int:
    symbol = binance.normalize_symbol(symbol)
    run_id = await db.create_run(user_id, symbol, timeframe, strategy_key, params,
                                 mode, fee_bps, slippage_bps, start_equity)
    _RUNS[run_id] = {"stop": False}
    _RUNS[run_id]["task"] = asyncio.create_task(_run_loop(run_id))
    return run_id


async def stop(run_id: int) -> bool:
    if run_id in _RUNS:
        _RUNS[run_id]["stop"] = True
        return True
    run = await db.get_run(run_id)
    if run and run["status"] == "running":
        await db.stop_run(run_id)
        return True
    return False


async def resume_all():
    for run in await db.all_running_runs():
        rid = run["id"]
        if rid not in _RUNS:
            _RUNS[rid] = {"stop": False}
            _RUNS[rid]["task"] = asyncio.create_task(_run_loop(rid))


def active_ids():
    return [rid for rid, st in _RUNS.items() if not st.get("stop")]
