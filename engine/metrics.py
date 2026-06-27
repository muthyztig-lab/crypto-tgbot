"""
Метрики ефективності — чистий Python, без numpy/pandas.

Свідомо рахуємо їх однаково і для бектесту, і для live equity-кривої, щоб
порівняння було чесним (одна формула — менше шансів, що "бектест бреше").
"""
import math


def _returns(equity):
    """По-барові прості дохідності з кривої капіталу."""
    out = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        out.append((equity[i] - prev) / prev if prev else 0.0)
    return out


def max_drawdown(equity):
    """Максимальна просадка кривої капіталу (частка, 0..1)."""
    peak, mdd = equity[0] if equity else 0.0, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def sharpe(equity, bars_per_year):
    """Річний Sharpe (rf=0) з по-барових дохідностей."""
    rets = _returns(equity)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(bars_per_year)


def cagr(equity, bars, bars_per_year):
    """Річна дохідність з урахуванням тривалості у барах."""
    if not equity or equity[0] <= 0 or bars <= 0:
        return 0.0
    years = bars / bars_per_year
    if years <= 0:
        return 0.0
    return (equity[-1] / equity[0]) ** (1 / years) - 1


def trade_stats(trades):
    """
    trades: список завершених угод зі словником {"pnl_pct": ..., "pnl_abs": ...}.
    Повертає win_rate, profit_factor, avg_win, avg_loss, expectancy.
    """
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "expectancy_pct": 0.0}
    wins = [t["pnl_pct"] for t in trades if t["pnl_pct"] > 0]
    losses = [t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0]
    gross_w = sum(t["pnl_abs"] for t in trades if t["pnl_abs"] > 0)
    gross_l = -sum(t["pnl_abs"] for t in trades if t["pnl_abs"] < 0)
    pf = (gross_w / gross_l) if gross_l > 0 else (float("inf") if gross_w > 0 else 0.0)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "profit_factor": round(pf, 2) if pf != float("inf") else 999.0,
        "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "expectancy_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 2),
    }


def summarize(equity, trades, bars_per_year):
    """Зведення метрик кривої капіталу + статистики угод."""
    total = (equity[-1] / equity[0] - 1) * 100 if equity and equity[0] else 0.0
    ts = trade_stats(trades)
    exposure = sum(1 for _ in trades)  # заповнюється детальніше у бектестері
    return {
        "total_return_pct": round(total, 2),
        "cagr_pct": round(cagr(equity, len(equity), bars_per_year) * 100, 2),
        "sharpe": round(sharpe(equity, bars_per_year), 2),
        "max_dd_pct": round(max_drawdown(equity) * 100, 2),
        "final_equity": round(equity[-1], 2) if equity else 0.0,
        **ts,
        "_exposure_trades": exposure,
    }
