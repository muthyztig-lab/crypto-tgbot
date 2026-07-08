import itertools

from engine import backtester


def _combos(grid):
    keys = list(grid)
    for values in itertools.product(*(grid[k] for k in keys)):
        combo = dict(zip(keys, values))
        if "fast" in combo and "slow" in combo and combo["fast"] >= combo["slow"]:
            continue
        if "low" in combo and "high" in combo and combo["low"] >= combo["high"]:
            continue
        yield combo


def _score(res):
    return res.summary.get("sharpe", 0.0) - 0.02 * res.summary.get("max_dd_pct", 0.0)


def optimize(strategy, candles, *, fee_bps, slippage_bps, latency_bars,
             start_equity, interval="1h", top_n=5):
    results = []
    for combo in _combos(strategy.grid):
        s = strategy.with_params(**combo)
        res = backtester.run_strategy(
            s, candles, fee_bps=fee_bps, slippage_bps=slippage_bps,
            latency_bars=latency_bars, start_equity=start_equity, interval=interval)
        results.append({
            "params": combo,
            "score": round(_score(res), 3),
            "sharpe": res.summary["sharpe"],
            "total_return_pct": res.summary["total_return_pct"],
            "max_dd_pct": res.summary["max_dd_pct"],
            "trades": res.summary["trades"],
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n], len(results)


def walk_forward(strategy, candles, *, fee_bps, slippage_bps, latency_bars,
                 start_equity, interval="1h", split=0.7):
    cut = int(len(candles) * split)
    in_sample, out_sample = candles[:cut], candles[cut:]
    if len(in_sample) < 50 or len(out_sample) < 30:
        return None

    top, _ = optimize(strategy, in_sample, fee_bps=fee_bps, slippage_bps=slippage_bps,
                      latency_bars=latency_bars, start_equity=start_equity,
                      interval=interval, top_n=1)
    if not top:
        return None
    best = top[0]
    s = strategy.with_params(**best["params"])
    oos = backtester.run_strategy(
        s, out_sample, fee_bps=fee_bps, slippage_bps=slippage_bps,
        latency_bars=latency_bars, start_equity=start_equity, interval=interval)
    return {
        "params": best["params"],
        "is_sharpe": best["sharpe"],
        "is_return_pct": best["total_return_pct"],
        "oos_sharpe": oos.summary["sharpe"],
        "oos_return_pct": oos.summary["total_return_pct"],
        "oos_max_dd_pct": oos.summary["max_dd_pct"],
        "overfit": best["sharpe"] > 0.5 and oos.summary["sharpe"] < 0,
    }
