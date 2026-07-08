import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core import db
from core import settings
from app.ratelimit import RateLimitMiddleware
from engine import backtester, optimizer, reconcile, runner
from engine.strategies import STRATEGIES, get_strategy
from exchange import binance

logging.basicConfig(level=logging.INFO)

if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.0)
        logging.info("Sentry увімкнено")
    except Exception:
        logging.warning("SENTRY_DSN заданий, але sentry-sdk недоступний")

if not settings.BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не заданий у .env (видає @BotFather).")

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())

DEFAULT_SYMBOL = "BTC"
DEFAULT_TF = "1h"
DEFAULT_STRAT = "ema_cross"

STRAT_ALIASES = {
    "ema": "ema_cross", "ema_cross": "ema_cross", "trend": "ema_cross",
    "rsi": "rsi_rev", "rsi_rev": "rsi_rev", "rev": "rsi_rev",
}


def _resolve_strat(key: str) -> str:
    return STRAT_ALIASES.get((key or "").lower(), key)


def _parse(text):
    parts = text.split()[1:]
    symbol = parts[0] if len(parts) > 0 else DEFAULT_SYMBOL
    strat = _resolve_strat(parts[1]) if len(parts) > 1 else DEFAULT_STRAT
    tf = parts[2].lower() if len(parts) > 2 else DEFAULT_TF
    if tf not in binance.INTERVALS:
        tf = DEFAULT_TF
    return symbol, strat, tf


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Бектест BTC (EMA)", callback_data="bt:BTC:ema_cross:1h"),
         InlineKeyboardButton(text="📊 Бектест ETH (RSI)", callback_data="bt:ETH:rsi_rev:1h")],
        [InlineKeyboardButton(text="🧪 Оптимізувати BTC", callback_data="opt:BTC:ema_cross:1h"),
         InlineKeyboardButton(text="📋 Стратегії", callback_data="strats")],
        [InlineKeyboardButton(text="▶️ Запуск BTC", callback_data="run:BTC:ema_cross:1h"),
         InlineKeyboardButton(text="📡 Статус", callback_data="status")],
    ])


def _fmt_params(params):
    return ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}"
                     for k, v in params.items())


def _two_col(label, a, b, suf=""):
    return f"{label:<14}{a + suf:>11}{b + suf:>13}"


def _fmt_backtest(strat, symbol, tf, candles):
    ideal = backtester.run_strategy(
        strat, candles, fee_bps=0, slippage_bps=0, latency_bars=0,
        start_equity=settings.START_EQUITY, interval=tf)
    real = backtester.run_strategy(
        strat, candles, fee_bps=settings.FEE_BPS, slippage_bps=settings.SLIPPAGE_BPS,
        latency_bars=settings.EXEC_LATENCY_BARS, start_equity=settings.START_EQUITY,
        interval=tf)
    bh = backtester.buy_hold(candles, settings.START_EQUITY)
    i, r = ideal.summary, real.summary
    gap = round(i["total_return_pct"] - r["total_return_pct"], 2)

    table = "\n".join([
        f"{'':<14}{'Ідеальний':>11}{'Реалістичн.':>13}",
        _two_col("Дохідність", f"{i['total_return_pct']:+.2f}",
                 f"{r['total_return_pct']:+.2f}", "%"),
        _two_col("Sharpe", f"{i['sharpe']:.2f}", f"{r['sharpe']:.2f}"),
        _two_col("Max DD", f"{i['max_dd_pct']:.2f}", f"{r['max_dd_pct']:.2f}", "%"),
        _two_col("Угод", f"{i['trades']}", f"{r['trades']}"),
        _two_col("Win rate", f"{i['win_rate']:.0f}", f"{r['win_rate']:.0f}", "%"),
        _two_col("Profit factor", f"{i['profit_factor']:.2f}", f"{r['profit_factor']:.2f}"),
        _two_col("Експозиція", f"{i['exposure_pct']:.0f}", f"{r['exposure_pct']:.0f}", "%"),
    ])
    return (
        f"📊 Backtest · {strat.name}\n"
        f"{symbol} {tf} · бари: {i['bars']} · параметри: {_fmt_params(strat.params)}\n"
        f"витрати: fee {settings.FEE_BPS:g}bps, slip {settings.SLIPPAGE_BPS:g}bps, "
        f"latency {settings.EXEC_LATENCY_BARS} бар\n"
        f"```\n{table}\n```\n"
        f"Buy & Hold: {bh['total_return_pct']:+.2f}%\n"
        f"Δ ідеал→реалізм: *{gap:+.2f}%* — стільки 'з'їдають' латентність і витрати.\n"
        f"_Реалістичні комісії: {r['fees_paid']:.2f} USDT, "
        f"slippage: {r['slippage_paid']:.2f} USDT._"
    )


def _fmt_optimize(strat, symbol, tf, candles):
    top, total = optimizer.optimize(
        strat, candles, fee_bps=settings.FEE_BPS, slippage_bps=settings.SLIPPAGE_BPS,
        latency_bars=settings.EXEC_LATENCY_BARS, start_equity=settings.START_EQUITY,
        interval=tf, top_n=5)
    wf = optimizer.walk_forward(
        strat, candles, fee_bps=settings.FEE_BPS, slippage_bps=settings.SLIPPAGE_BPS,
        latency_bars=settings.EXEC_LATENCY_BARS, start_equity=settings.START_EQUITY,
        interval=tf)

    rows = [f"{'#':<2}{'параметри':<22}{'Sharpe':>7}{'Ret%':>8}{'DD%':>7}{'угод':>6}"]
    for n, rr in enumerate(top, 1):
        rows.append(f"{n:<2}{_fmt_params(rr['params'])[:21]:<22}"
                    f"{rr['sharpe']:>7.2f}{rr['total_return_pct']:>8.1f}"
                    f"{rr['max_dd_pct']:>7.1f}{rr['trades']:>6}")
    out = [f"🧪 Оптимізація · {strat.name} · {symbol} {tf}",
           f"перебрано {total} конфігурацій (реалістичні витрати)",
           "```", "\n".join(rows), "```"]
    if wf:
        flag = "⚠️ ПЕРЕПІДГОНКА" if wf["overfit"] else "✅ тримається"
        out.append(
            f"*Walk-forward* (70% підбір / 30% перевірка): {flag}\n"
            f"Найкращі: {_fmt_params(wf['params'])}\n"
            f"IS Sharpe {wf['is_sharpe']:.2f} (ret {wf['is_return_pct']:+.1f}%) → "
            f"OOS Sharpe {wf['oos_sharpe']:.2f} (ret {wf['oos_return_pct']:+.1f}%)")
    else:
        out.append("_Замало даних для walk-forward на цьому таймфреймі._")
    return "\n".join(out)


def _fmt_report(rep):
    if "error" in rep:
        return "🔬 " + rep["error"]
    run, ret, gap = rep["run"], rep["returns"], rep["gap"]
    table = "\n".join([
        f"{'Ідеал (lat0,fee0)':<22}{ret['ideal']:+.2f}%",
        f"{'+латентність 1 бар':<22}{ret['with_timing']:+.2f}%",
        f"{'+комісії+slippage':<22}{ret['with_costs']:+.2f}%",
        f"{'LIVE (факт)':<22}{ret['live']:+.2f}%",
        f"{'Buy & Hold':<22}{ret['buy_hold']:+.2f}%",
    ])
    return (
        f"🔬 Reconcile #{run['id']} · {rep['strategy_name']}\n"
        f"{run['symbol']} {run['timeframe']} [{run['mode']}] · "
        f"бари: {rep['bars']}, виконань: {rep['live_fills']}\n"
        f"```\n{table}\n```\n"
        f"*Execution gap (ідеал→live): {gap['total']:+.2f}%*\n"
        f"├ запізнення виконання: {gap['timing_cost']:+.2f}%\n"
        f"├ комісії+проковзування: {gap['cost_cost']:+.2f}%\n"
        f"└ residual (інфраструктура): {gap['residual']:+.2f}%\n"
        f"_факт. комісії {rep['live_fees_usdt']:.4f} USDT · "
        f"факт. slippage {rep['live_slippage_usdt']:.4f} USDT_\n\n"
        f"📝 {rep['verdict']}"
    )


async def _live_metrics(run):
    pts = await db.list_equity(run["id"])
    if not pts:
        return run["start_equity"], 0.0
    eq = pts[-1]["equity"]
    ret = (eq / run["start_equity"] - 1) * 100 if run["start_equity"] else 0.0
    return eq, ret


async def _candles(symbol, tf, limit=500):
    return await asyncio.to_thread(binance.fetch_klines, symbol, tf, limit)


async def _reply(target, text):
    try:
        await target.answer(text, parse_mode="Markdown",
                            disable_web_page_preview=True)
    except Exception:
        await target.answer(text)


async def _do_backtest(target, symbol, key, tf):
    try:
        strat = get_strategy(key)
    except KeyError as e:
        await target.answer(f"⚠️ {e}")
        return
    m = await target.answer(f"⏳ Бектест {symbol} {tf}…")
    try:
        candles = await _candles(symbol, tf, 500)
        if len(candles) < strat.warmup() + 20:
            await m.edit_text("Замало історії для цього таймфрейму.")
            return
        text = _fmt_backtest(strat, binance.normalize_symbol(symbol), tf, candles)
        await m.delete()
        await _reply(target, text)
    except binance.ExchangeError as e:
        await m.edit_text(f"⚠️ {e}")
    except Exception:
        logging.exception("backtest failed")
        await m.edit_text("⚠️ Помилка бектесту. Перевір символ/таймфрейм.")


async def _do_optimize(target, symbol, key, tf):
    try:
        strat = get_strategy(key)
    except KeyError as e:
        await target.answer(f"⚠️ {e}")
        return
    m = await target.answer(f"⏳ Оптимізую {symbol} {tf} (це може зайняти час)…")
    try:
        candles = await _candles(symbol, tf, 800)
        if len(candles) < 120:
            await m.edit_text("Замало історії для оптимізації.")
            return
        text = await asyncio.to_thread(
            _fmt_optimize, strat, binance.normalize_symbol(symbol), tf, candles)
        await m.delete()
        await _reply(target, text)
    except binance.ExchangeError as e:
        await m.edit_text(f"⚠️ {e}")
    except Exception:
        logging.exception("optimize failed")
        await m.edit_text("⚠️ Помилка оптимізації.")


async def _do_run(target, user_id, symbol, key, tf):
    if not settings.is_admin(user_id):
        await target.answer("⛔ Запуск торгівлі дозволено лише адмінам "
                            "(ADMIN_IDS у .env).")
        return
    try:
        strat = get_strategy(key)
    except KeyError as e:
        await target.answer(f"⚠️ {e}")
        return
    mode = settings.TRADE_MODE
    note = ""
    if mode == "live" and not settings.can_trade_live():
        mode, note = "paper", "\n_(TRADE_MODE=live, але нема ключів Binance → paper)_"
    run_id = await runner.start_run(
        user_id=user_id, symbol=symbol, timeframe=tf, strategy_key=strat.key,
        params=strat.params, mode=mode, fee_bps=settings.FEE_BPS,
        slippage_bps=settings.SLIPPAGE_BPS, start_equity=settings.START_EQUITY)
    venue = ""
    if mode == "live":
        venue = " Testnet" if settings.BINANCE_TESTNET else " Mainnet"
    if mode == "live" and settings.BINANCE_TESTNET:
        note += ("\n_На testnet комісії та slippage ≈ 0 (тонкий стакан), тож live "
                 "виглядатиме краще за реалістичний бектест — це очікувано._")
    await _reply(target,
                 f"▶️ Прогін *#{run_id}* запущено: {strat.name} · "
                 f"{binance.normalize_symbol(symbol)} {tf} · [{mode}{venue}].\n"
                 f"Угоди приходитимуть сюди. "
                 f"`/status`, `/report {run_id}`, `/stop {run_id}`.{note}")


async def _send_status(target, user_id):
    runs = await db.list_runs(user_id, status="running")
    if not runs:
        await _reply(target, "Немає активних прогонів. Запусти: `/run BTC ema 1h`")
        return
    rows = []
    for r in runs:
        eq, ret = await _live_metrics(r)
        pos = "LONG" if r["last_pos"] > 0 else "flat"
        rows.append(f"#{r['id']} {r['symbol']:<9}{r['timeframe']:<4}"
                    f"{r['strategy'][:8]:<9}{pos:<5}{eq:>9.2f} ({ret:+.2f}%)")
    await _reply(target, "📡 *Активні прогони*\n```\n" + "\n".join(rows) +
                 "\n```\nЗвіт: `/report ID` · Стоп: `/stop ID`")


async def _send_strategies(target):
    lines = ["📋 *Стратегії*", ""]
    for s in STRATEGIES.values():
        lines.append(f"• `{s.key}` — *{s.name}*\n  {s.desc}\n"
                     f"  параметри: {_fmt_params(s.params)}")
    await _reply(target, "\n".join(lines))


def _mode_line() -> str:
    mode = settings.TRADE_MODE
    if mode == "live" and settings.can_trade_live():
        net = "Testnet" if settings.BINANCE_TESTNET else "Mainnet"
        return f"*live* — реальні ордери на Binance {net}"
    if mode == "live":
        return "*paper* (TRADE_MODE=live, але нема ключів Binance)"
    return "*paper* — симуляція виконання на реальних даних Binance"


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🤖 *Algo-Trading R&D Bot*\n"
        "Дослідницька платформа: дані → бектест → оптимізація → live → reconcile.\n\n"
        f"Режим: {_mode_line()}.\n\n"
        "Швидкий старт:\n"
        "• `/backtest BTC ema 1h` — бектест (ідеал vs реалізм)\n"
        "• `/optimize BTC ema 1h` — підбір параметрів + walk-forward\n"
        "• `/run BTC ema 1h` — запустити прогін\n"
        "• `/status` · `/report <id>` · `/stop <id>`\n\n"
        "`/help` — повна довідка.",
        parse_mode="Markdown", reply_markup=main_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await _reply(
        message,
        "*Команди*\n"
        "`/strategies` — стратегії та параметри\n"
        "`/backtest SYM STRAT [TF]` — бектест на історії Binance\n"
        "`/optimize SYM STRAT [TF]` — grid search + walk-forward\n"
        "`/run SYM STRAT [TF]` — live-прогін (paper/Binance)\n"
        "`/status` — активні прогони · `/runs` — історія\n"
        "`/stop ID` — зупинити · `/report ID` — reconcile (execution gap)\n"
        "`/mode` — режим виконання та витрати\n\n"
        f"STRAT: {', '.join(STRATEGIES)} (аліаси: ema, rsi)\n"
        f"TF: {', '.join(binance.INTERVALS)}\n\n"
        "_Backtest показує два числа: ідеальне (вхід на закритті, без витрат) і "
        "реалістичне (вхід на наступному відкритті + комісії + slippage). "
        "Reconcile потім розкладає, чому live відрізняється від обох._")


@dp.message(Command("strategies"))
async def cmd_strategies(message: Message):
    await _send_strategies(message)


@dp.message(Command("mode"))
async def cmd_mode(message: Message):
    keys = "є" if settings.can_trade_live() else "нема"
    await _reply(
        message,
        "*Режим виконання*\n"
        f"{_mode_line()}\n"
        f"TRADE_MODE: `{settings.TRADE_MODE}` · ключі Binance: {keys}\n"
        f"fee: {settings.FEE_BPS:g} bps · slippage: {settings.SLIPPAGE_BPS:g} bps · "
        f"latency: {settings.EXEC_LATENCY_BARS} бар\n"
        f"стартовий капітал: {settings.START_EQUITY:g} USDT · "
        f"полінг: {settings.POLL_SECONDS} c")


@dp.message(Command("backtest"))
async def cmd_backtest(message: Message):
    symbol, key, tf = _parse(message.text)
    await _do_backtest(message, symbol, key, tf)


@dp.message(Command("optimize"))
async def cmd_optimize(message: Message):
    symbol, key, tf = _parse(message.text)
    await _do_optimize(message, symbol, key, tf)


@dp.message(Command("run"))
async def cmd_run(message: Message):
    symbol, key, tf = _parse(message.text)
    await _do_run(message, message.from_user.id, symbol, key, tf)


@dp.message(Command("status"))
async def cmd_status(message: Message):
    await _send_status(message, message.from_user.id)


@dp.message(Command("runs"))
async def cmd_runs(message: Message):
    runs = await db.list_runs(message.from_user.id)
    if not runs:
        await message.answer("Прогонів ще не було.")
        return
    rows = []
    for r in runs[:20]:
        _, ret = await _live_metrics(r)
        rows.append(f"#{r['id']} {r['status']:<8}{r['symbol']:<9}{r['timeframe']:<4}"
                    f"{r['strategy'][:8]:<9}{ret:+.2f}%")
    await _reply(message, "🗂 *Історія прогонів*\n```\n" + "\n".join(rows) + "\n```")


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await _reply(message, "Формат: `/stop ID`")
        return
    run_id = int(parts[1])
    run = await db.get_run(run_id)
    if not run or run["user_id"] != message.from_user.id:
        await message.answer("Прогін не знайдено.")
        return
    ok = await runner.stop(run_id)
    await message.answer(f"⏹ Прогін #{run_id} {'зупиняється' if ok else 'уже зупинений'}.")


@dp.message(Command("report"))
async def cmd_report(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await _reply(message, "Формат: `/report ID`")
        return
    await _do_report(message, message.from_user.id, int(parts[1]))


async def _do_report(target, user_id, run_id):
    run = await db.get_run(run_id)
    if not run or run["user_id"] != user_id:
        await target.answer("Прогін не знайдено.")
        return
    m = await target.answer("🔬 Рахую reconcile…")
    try:
        rep = await reconcile.reconcile(run_id)
        await m.delete()
        await _reply(target, _fmt_report(rep))
    except Exception:
        logging.exception("report failed")
        await m.edit_text("⚠️ Помилка reconcile.")


@dp.callback_query(F.data == "strats")
async def cb_strats(call: CallbackQuery):
    await call.answer()
    await _send_strategies(call.message)


@dp.callback_query(F.data == "status")
async def cb_status(call: CallbackQuery):
    await call.answer()
    await _send_status(call.message, call.from_user.id)


@dp.callback_query(F.data.startswith("bt:"))
async def cb_bt(call: CallbackQuery):
    _, sym, key, tf = call.data.split(":")
    await call.answer("Бектест…")
    await _do_backtest(call.message, sym, key, tf)


@dp.callback_query(F.data.startswith("opt:"))
async def cb_opt(call: CallbackQuery):
    _, sym, key, tf = call.data.split(":")
    await call.answer("Оптимізація…")
    await _do_optimize(call.message, sym, key, tf)


@dp.callback_query(F.data.startswith("run:"))
async def cb_run(call: CallbackQuery):
    _, sym, key, tf = call.data.split(":")
    await call.answer("Запуск…")
    await _do_run(call.message, call.from_user.id, sym, key, tf)


async def _notify(run_id, text):
    run = await db.get_run(run_id)
    if run:
        try:
            await bot.send_message(run["user_id"], text)
        except Exception:
            logging.warning("notify: не вдалося надіслати в %s", run.get("user_id"))


async def main():
    await db.init()
    logging.info("Фічі: %s", settings.feature_status())
    runner.set_notifier(_notify)
    await runner.resume_all()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
