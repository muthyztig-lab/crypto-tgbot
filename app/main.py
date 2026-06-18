import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from aiogram.types import LabeledPrice, PreCheckoutQuery  # noqa: F401

from app import alerts
from core import storage
from core import db
from core import settings
from render import cards
from app import payments
from sources import onchain
from sources import derivatives
from analytics import indicators
from analytics import backtest
from sources import news
from analytics import ai
from analytics import portfolio
from core.i18n import t
from app.ratelimit import RateLimitMiddleware
from analytics.analysis import full_analysis, support_resistance, updated_at
from sources.market_data import (
    DEFAULT_TIMEFRAME,
    POPULAR_COINS,
    TIMEFRAME_ROWS,
    TIMEFRAMES,
    DataUnavailable,
    get_candles_for_timeframe,
    get_fear_greed,
    get_global_overview,
    get_history_for_timeframe,
    get_market_info,
    get_price_history,
    get_top_movers,
    search_coin,
)
from analytics.signals import long_short_signal
from render.svg_render import (
    build_alert_svg,  # noqa: F401  (використовується модулем alerts)
    build_analysis_svg,
    build_market_svg,
    build_movers_svg,
    build_signal_svg,
    svg_to_png_bytes,
)

logging.basicConfig(level=logging.INFO)

if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.0)
        logging.info("Sentry-моніторинг увімкнено")
    except Exception:
        logging.warning("SENTRY_DSN заданий, але sentry-sdk недоступний")

if not settings.BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN не заданий. Додайте BOT_TOKEN=... у файл .env "
        "(токен видає @BotFather у Telegram)."
    )

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

dp.message.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())

ALERT_THRESHOLDS = [0.5, 1, 2, 3, 5, 10]

chat_state: dict = {}
MAX_CHAT_STATES = 5000


def _state(chat_id: int) -> dict:
    st = chat_state.get(chat_id)
    if st is None:
        if len(chat_state) >= MAX_CHAT_STATES:
            chat_state.pop(next(iter(chat_state)), None)
        st = {"coin": None, "tf": DEFAULT_TIMEFRAME, "mode": "line", "messages": []}
        chat_state[chat_id] = st
    return st


async def _cleanup_messages(chat_id: int) -> None:
    """Видаляє всі відстежувані повідомлення в чаті (щоб не засмічувати)."""
    st = _state(chat_id)
    for mid in st["messages"]:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
    st["messages"] = []


def _track(chat_id: int, message: Message) -> None:
    """Запам'ятовує повідомлення для майбутнього автовидалення."""
    _state(chat_id)["messages"].append(message.message_id)


def coins_keyboard() -> InlineKeyboardMarkup:
    """Головне меню вибору монети + швидкі розділи."""
    tickers = list(POPULAR_COINS.keys())
    rows = []
    for i in range(0, len(tickers), 5):
        rows.append(
            [
                InlineKeyboardButton(text=t, callback_data=f"coin:{POPULAR_COINS[t]}")
                for t in tickers[i : i + 5]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Огляд ринку", callback_data="market"),
            InlineKeyboardButton(text="Топ 24г", callback_data="top"),
            InlineKeyboardButton(text="Обране", callback_data="favs"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="📰 Новини", callback_data="news"),
            InlineKeyboardButton(text="💼 Портфель", callback_data="portfolio"),
            InlineKeyboardButton(text="⭐ PRO", callback_data="upgrade"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def analysis_keyboard(coin_id: str, tf_key: str, mode: str) -> InlineKeyboardMarkup:
    """Клавіатура під карткою аналізу: таймфрейми (1хв..1р) + дії."""
    tf_rows = []
    for row_keys in TIMEFRAME_ROWS:
        tf_rows.append(
            [
                InlineKeyboardButton(
                    text=(f"[{TIMEFRAMES[k]['short']}]" if k == tf_key
                          else TIMEFRAMES[k]["short"]),
                    callback_data=f"tf:{coin_id}:{k}",
                )
                for k in row_keys
            ]
        )

    next_mode = "candle" if mode == "line" else "line"
    mode_label = "Свічковий графік" if mode == "line" else "Лінійний графік"
    mode_buttons = [
        InlineKeyboardButton(
            text=mode_label, callback_data=f"mode:{coin_id}:{tf_key}:{next_mode}"
        )
    ]

    rows = [
        *tf_rows,
        mode_buttons
        + [
            InlineKeyboardButton(text="Оновити", callback_data=f"tf:{coin_id}:{tf_key}"),
            InlineKeyboardButton(text="Сигнал LONG/SHORT", callback_data=f"sig:{coin_id}"),
        ],
        [
            InlineKeyboardButton(text="Деривативи", callback_data=f"deriv:{coin_id}"),
            InlineKeyboardButton(text="Тех.сигнали", callback_data=f"conf:{coin_id}"),
            InlineKeyboardButton(text="Бектест", callback_data=f"bt:{coin_id}"),
        ],
        [
            InlineKeyboardButton(text="AI-пояснення", callback_data=f"ai:{coin_id}"),
            InlineKeyboardButton(text="В обране + сповіщення", callback_data=f"fav:{coin_id}"),
            InlineKeyboardButton(text="Інша монета", callback_data="menu"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def threshold_keyboard(coin_id: str) -> InlineKeyboardMarkup:
    """Вибір порогу % для сповіщень про зміну ціни."""
    row1 = [
        InlineKeyboardButton(text=f"{p}%", callback_data=f"favset:{coin_id}:{p}")
        for p in ALERT_THRESHOLDS[:3]
    ]
    row2 = [
        InlineKeyboardButton(text=f"{p}%", callback_data=f"favset:{coin_id}:{p}")
        for p in ALERT_THRESHOLDS[3:]
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def favorites_keyboard(favs: dict) -> InlineKeyboardMarkup:
    """Список обраного: відкрити монету або видалити її."""
    rows = []
    for coin_id, fav in favs.items():
        rows.append(
            [
                InlineKeyboardButton(
                    text=f'{fav["symbol"]} (поріг {fav["threshold_pct"]}%)',
                    callback_data=f"coin:{coin_id}",
                ),
                InlineKeyboardButton(
                    text="Видалити", callback_data=f"favdel:{coin_id}"
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="Меню монет", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_analysis(chat_id: int, coin_id: str, tf_key: str = None,
                        mode: str = None) -> None:
    """Збирає дані, рендерить картку аналізу та надсилає її."""
    st = _state(chat_id)

    if st["coin"] != coin_id:
        st["tf"], st["mode"] = DEFAULT_TIMEFRAME, "line"

    tf_key = tf_key or st["tf"]
    mode = mode or st["mode"]
    if tf_key not in TIMEFRAMES:
        tf_key = DEFAULT_TIMEFRAME

    info = await asyncio.to_thread(get_market_info, coin_id)
    chart_hist = await asyncio.to_thread(
        get_history_for_timeframe, coin_id, tf_key, info["symbol"]
    )
    risk_hist = await asyncio.to_thread(get_price_history, coin_id, 30)
    fng = await asyncio.to_thread(get_fear_greed)
    ohlc = None
    if mode == "candle":
        ohlc = await asyncio.to_thread(
            get_candles_for_timeframe, coin_id, tf_key, info["symbol"]
        )

    a = full_analysis(info, chart_hist, risk_hist, TIMEFRAMES[tf_key]["label"])
    if ohlc:
        a["support"], a["resistance"] = support_resistance([c[4] for c in ohlc])
    png = svg_to_png_bytes(build_analysis_svg(a, mode, ohlc, fng))

    await _cleanup_messages(chat_id)

    msg = await bot.send_photo(
        chat_id,
        BufferedInputFile(png, filename=f'{info["symbol"]}_analysis.png'),
        caption=(
            f'{info["name"]} ({info["symbol"]}) | {TIMEFRAMES[tf_key]["label"]}\n'
            f'Ризик: {a["risk_score"]}/100 — {a["risk_category"]}\n'
            f'Оновлено: {a["updated_at"]}'
        ),
        reply_markup=analysis_keyboard(coin_id, tf_key, mode),
    )
    _track(chat_id, msg)
    st["coin"], st["tf"], st["mode"] = coin_id, tf_key, mode


async def send_signal(chat_id: int, coin_id: str) -> None:
    """Рендерить та надсилає картку сигналу LONG/SHORT."""
    info = await asyncio.to_thread(get_market_info, coin_id)
    risk_hist = await asyncio.to_thread(get_price_history, coin_id, 30)
    a = full_analysis(info, risk_hist, risk_hist, "30 днів")
    sig = long_short_signal(a["risk_prices"], info["change_24h_pct"], info["price"])

    png = svg_to_png_bytes(build_signal_svg(a, sig))
    sl = f' | SL {sig["stop_loss"]:.6g}' if sig["stop_loss"] else ""
    tp = f' | TP {sig["take_profit"]:.6g}' if sig["take_profit"] else ""
    msg = await bot.send_photo(
        chat_id,
        BufferedInputFile(png, filename=f'{info["symbol"]}_signal.png'),
        caption=(
            f'{info["name"]} ({info["symbol"]}): {sig["direction"]} '
            f'(впевненість {sig["confidence"]}%){sl}{tp}\n'
            f'Оновлено: {a["updated_at"]}\nНе є фінансовою порадою.'
        ),
        reply_markup=analysis_keyboard(coin_id, _state(chat_id)["tf"],
                                       _state(chat_id)["mode"]),
    )
    _track(chat_id, msg)


async def send_market(chat_id: int) -> None:
    """Картка глобального огляду ринку."""
    g = await asyncio.to_thread(get_global_overview)
    fng = await asyncio.to_thread(get_fear_greed)
    png = svg_to_png_bytes(build_market_svg(g, fng, updated_at()))
    await _cleanup_messages(chat_id)
    msg = await bot.send_photo(
        chat_id,
        BufferedInputFile(png, filename="market.png"),
        caption=f"Огляд крипторинку | Оновлено: {updated_at()}",
        reply_markup=coins_keyboard(),
    )
    _track(chat_id, msg)


async def send_top(chat_id: int) -> None:
    """Картка топ зростання/падіння за 24 години."""
    gainers, losers = await asyncio.to_thread(get_top_movers, 5)
    png = svg_to_png_bytes(build_movers_svg(gainers, losers, updated_at()))
    await _cleanup_messages(chat_id)
    msg = await bot.send_photo(
        chat_id,
        BufferedInputFile(png, filename="top_movers.png"),
        caption=f"Топ руху за 24 години | Оновлено: {updated_at()}",
        reply_markup=coins_keyboard(),
    )
    _track(chat_id, msg)


async def send_favorites(chat_id: int) -> None:
    """Список обраних монет із порогами сповіщень."""
    favs = storage.get_favorites(chat_id)
    await _cleanup_messages(chat_id)
    if not favs:
        msg = await bot.send_message(
            chat_id,
            "Обране порожнє. Відкрийте монету та натисніть "
            "\"В обране + сповіщення\".",
            reply_markup=coins_keyboard(),
        )
    else:
        lines = ["Ваше обране (сповіщення при зміні ціни на поріг):", ""]
        for fav in favs.values():
            lines.append(
                f'- {fav["name"]} ({fav["symbol"]}): поріг {fav["threshold_pct"]}%, '
                f'орієнтир {fav["ref_price"]:.6g} USD'
            )
        msg = await bot.send_message(
            chat_id, "\n".join(lines), reply_markup=favorites_keyboard(favs)
        )
    _track(chat_id, msg)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    _track(message.chat.id, message)
    ref = 0
    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) != message.from_user.id:
        ref = int(parts[1])
    await db.ensure_user(message.from_user.id, ref)
    msg = await message.answer(
        "Аналіз ринку криптовалют та оцінка ризиків.\n\n"
        "Оберіть монету кнопкою нижче або надішліть тикер чи назву "
        "(наприклад: BTC, ethereum, ton).\n\n"
        "Основне: /market, /top, /favorites\n"
        "On-chain ризик токена: /risk eth <адреса>\n"
        "Деривативи: /deriv BTC · Тех.сигнали: /signals BTC\n"
        "Бектест: /backtest BTC · Новини: /news\n"
        "Портфель: /portfolio, /addcoin BTC 0.5 60000\n"
        "Алерти: /alert BTC price > 70000, /alerts\n"
        "AI (PRO): /ask · PRO: /upgrade · Мова: /lang en\n"
        "/help — повна довідка.",
        reply_markup=coins_keyboard(),
    )
    _track(message.chat.id, msg)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    _track(message.chat.id, message)
    msg = await message.answer(
        "Що вміє бот:\n\n"
        "1. Аналіз монети: ціна, графік (1 хвилина - 1 рік, лінія або\n"
        "   свічки на будь-якому таймфреймі),\n"
        "   рівні підтримки/опору, ризик-бал 0-100, RSI, волатильність,\n"
        "   тренд, просадка, Fear & Greed Index.\n"
        "2. Сигнал LONG / SHORT: бот зважує тренд, RSI, momentum і добову\n"
        "   зміну, обирає найвигідніший напрямок та рахує Stop Loss /\n"
        "   Take Profit за ATR.\n"
        "3. Обране та сповіщення: додайте монету в обране, оберіть поріг\n"
        "   у % — бот напише, щойно ціна зміниться на цей відсоток.\n"
        "4. /market — огляд усього ринку, /top — топ зростання і падіння.\n"
        "5. При виборі іншої монети старі повідомлення видаляються\n"
        "   автоматично, щоб не засмічувати чат.\n\n"
        "PRO-функції:\n"
        "• On-chain ризик токена (honeypot, податки, права власника,\n"
        "  блокування ліквідності): /risk eth 0x...\n"
        "• Деривативи (funding, OI, long/short): /deriv BTC\n"
        "• Тех.сигнали (MACD, Bollinger, дивергенції): /signals BTC\n"
        "• Бектест стратегій: /backtest BTC\n"
        "• Новини + сентимент: /news [тикер]\n"
        "• Портфель: /portfolio, /addcoin BTC 0.5 60000, /delcoin <id>\n"
        "• Алерти-правила: /alert BTC price > 70000, /alerts, /delalert <id>\n"
        "• Watchlist: /watch BTC, /watchlist\n"
        "• AI-помічник (PRO): /ask <питання>\n"
        "• PRO-підписка: /upgrade, статус: /pro\n"
        "• Мова інтерфейсу: /lang uk | /lang en\n\n"
        "Дані: CoinGecko + OKX + GoPlus (без обов'язкових ключів). "
        "Нічого з цього не є фінансовою порадою.",
        reply_markup=coins_keyboard(),
    )
    _track(message.chat.id, msg)


@dp.message(Command("market"))
async def cmd_market(message: Message):
    _track(message.chat.id, message)
    await send_market(message.chat.id)


@dp.message(Command("top"))
async def cmd_top(message: Message):
    _track(message.chat.id, message)
    await send_top(message.chat.id)


@dp.message(Command("favorites"))
async def cmd_favorites(message: Message):
    _track(message.chat.id, message)
    await send_favorites(message.chat.id)


async def _send_error(chat_id: int, e: Exception) -> None:
    """Зрозуміле повідомлення про помилку (теж відстежується для видалення)."""
    if isinstance(e, DataUnavailable):
        text = str(e)
    else:
        logging.exception("Помилка обробки запиту в чаті %s", chat_id)
        text = ("Не вдалося отримати дані. Спробуйте ще раз за хвилину "
                "або оберіть іншу монету/таймфрейм.")
    msg = await bot.send_message(chat_id, text)
    _track(chat_id, msg)

@dp.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await _cleanup_messages(call.message.chat.id)
    _state(call.message.chat.id)["coin"] = None
    msg = await call.message.answer("Оберіть монету:", reply_markup=coins_keyboard())
    _track(call.message.chat.id, msg)
    await call.answer()


@dp.callback_query(F.data == "market")
async def cb_market(call: CallbackQuery):
    await call.answer("Завантажую огляд ринку...")
    try:
        await send_market(call.message.chat.id)
    except Exception as e:
        logging.exception("market failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data == "top")
async def cb_top(call: CallbackQuery):
    await call.answer("Завантажую топ руху...")
    try:
        await send_top(call.message.chat.id)
    except Exception as e:
        logging.exception("top failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data == "favs")
async def cb_favs(call: CallbackQuery):
    await call.answer()
    await send_favorites(call.message.chat.id)


@dp.callback_query(F.data.startswith("coin:"))
async def cb_coin(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    await call.answer("Завантажую дані...")
    try:
        await send_analysis(call.message.chat.id, coin_id)
    except Exception as e:
        logging.exception("analysis failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("tf:"))
async def cb_timeframe(call: CallbackQuery):
    _, coin_id, tf_key = call.data.split(":", 2)
    await call.answer("Оновлюю графік...")
    try:
        await send_analysis(call.message.chat.id, coin_id, tf_key=tf_key)
    except Exception as e:
        logging.exception("timeframe failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("mode:"))
async def cb_mode(call: CallbackQuery):
    _, coin_id, tf_key, mode = call.data.split(":", 3)
    await call.answer("Перемикаю графік...")
    try:
        await send_analysis(call.message.chat.id, coin_id, tf_key=tf_key, mode=mode)
    except Exception as e:
        logging.exception("mode failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("sig:"))
async def cb_signal(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    await call.answer("Рахую сигнал...")
    try:
        await send_signal(call.message.chat.id, coin_id)
    except Exception as e:
        logging.exception("signal failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("fav:"))
async def cb_fav(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    msg = await call.message.answer(
        "Оберіть поріг зміни ціни, при якому надсилати сповіщення:",
        reply_markup=threshold_keyboard(coin_id),
    )
    _track(call.message.chat.id, msg)
    await call.answer()


@dp.callback_query(F.data.startswith("favset:"))
async def cb_favset(call: CallbackQuery):
    _, coin_id, pct = call.data.split(":", 2)
    try:
        info = await asyncio.to_thread(get_market_info, coin_id)
        storage.add_favorite(
            user_id=call.message.chat.id,
            coin_id=coin_id,
            symbol=info["symbol"],
            name=info["name"],
            threshold_pct=float(pct),
            ref_price=info["price"],
        )
        msg = await call.message.answer(
            f'{info["name"]} ({info["symbol"]}) додано в обране.\n'
            f'Сповіщення прийде при зміні ціни на {pct}% '
            f'від {info["price"]:.6g} USD (перевірка щохвилини).'
        )
        _track(call.message.chat.id, msg)
        await call.answer("Додано в обране")
    except Exception as e:
        logging.exception("favset failed")
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("favdel:"))
async def cb_favdel(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    removed = storage.remove_favorite(call.message.chat.id, coin_id)
    await call.answer("Видалено" if removed else "Вже видалено")
    await send_favorites(call.message.chat.id)


def upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"⭐ Купити PRO ({settings.PRO_PRICE_STARS} Stars)",
                             callback_data="buy_pro"),
    ], [InlineKeyboardButton(text="Меню", callback_data="menu")]])


async def _require_pro(chat_id: int, user_id: int) -> bool:
    if await db.is_pro(user_id):
        return True
    lang = await db.get_lang(user_id)
    msg = await bot.send_message(chat_id, t(lang, "pro_only"),
                                 reply_markup=upgrade_keyboard())
    _track(chat_id, msg)
    return False


async def _send_card_photo(chat_id: int, svg: str, fname: str, caption: str) -> None:
    png = await asyncio.to_thread(svg_to_png_bytes, svg)
    msg = await bot.send_photo(
        chat_id, BufferedInputFile(png, filename=fname), caption=caption)
    _track(chat_id, msg)


async def send_onchain(chat_id: int, chain: str, address: str) -> None:
    r = await asyncio.to_thread(onchain.token_security, chain, address)
    svg = cards.build_onchain_card(r, updated_at())
    cap = (f"On-chain: {r['name']} ({r['symbol']}) — ризик {r['score']:.0f}/100 "
           f"({r['category']}). Не є фінансовою порадою.")
    await _send_card_photo(chat_id, svg, "onchain.png", cap)


async def send_deriv(chat_id: int, coin_id: str) -> None:
    info = await asyncio.to_thread(get_market_info, coin_id)
    d = await asyncio.to_thread(derivatives.derivatives_overview, info["symbol"])
    svg = cards.build_derivatives_card(d, updated_at())
    await _send_card_photo(chat_id, svg, "deriv.png",
                           f"Деривативи {d['symbol']} (OKX).")


async def send_confluence(chat_id: int, coin_id: str) -> None:
    info = await asyncio.to_thread(get_market_info, coin_id)
    hist = await asyncio.to_thread(get_price_history, coin_id, 30)
    c = indicators.confluence([p[1] for p in hist])
    svg = cards.build_confluence_card(info["symbol"], c, updated_at())
    await _send_card_photo(chat_id, svg, "signals.png",
                           f"{info['symbol']}: {c['verdict']} ({c['score']:+.0f}). "
                           f"Не є фінансовою порадою.")


async def send_backtest(chat_id: int, coin_id: str) -> None:
    info = await asyncio.to_thread(get_market_info, coin_id)
    hist = await asyncio.to_thread(get_price_history, coin_id, 30)
    bt = backtest.run([p[1] for p in hist])
    svg = cards.build_backtest_card(info["symbol"], bt, updated_at())
    await _send_card_photo(chat_id, svg, "backtest.png",
                           f"Бектест {info['symbol']} (історія, не прогноз).")


async def send_news(chat_id: int, currency: str = "") -> None:
    n = await asyncio.to_thread(news.get_news, currency, 6)
    svg = cards.build_news_card(n, updated_at())
    await _send_card_photo(chat_id, svg, "news.png",
                           f"Крипто-новини · сентимент: {n['sentiment']}")


async def send_portfolio(chat_id: int, user_id: int) -> None:
    p = await portfolio.compute(user_id)
    if p["empty"]:
        lang = await db.get_lang(user_id)
        msg = await bot.send_message(chat_id, t(lang, "portfolio_empty"))
        _track(chat_id, msg)
        return
    svg = cards.build_portfolio_card(p, updated_at())
    await _send_card_photo(chat_id, svg, "portfolio.png",
                           f"Портфель: {p['total_pnl_pct']:+.1f}% P&L")


@dp.message(Command("risk"))
async def cmd_risk(message: Message):
    _track(message.chat.id, message)
    args = (message.text.split(maxsplit=2) + ["", ""])[1:3]
    chain, address = args[0], args[1]
    if not chain or not address:
        msg = await message.answer(
            "On-chain перевірка токена.\nФормат: /risk <мережа> <адреса>\n"
            "Напр.: /risk eth 0xdAC17F958D2ee523a2206206994597C13D831ec7\n"
            f"Мережі: {', '.join(sorted(set(onchain.CHAINS)))}")
        _track(message.chat.id, msg)
        return
    try:
        await send_onchain(message.chat.id, chain, address)
    except onchain.OnchainUnavailable as e:
        m = await message.answer(str(e)); _track(message.chat.id, m)
    except Exception as e:
        await _send_error(message.chat.id, e)


async def _coin_cmd(message: Message, sender):
    """Спільний шаблон для команд, що приймають тикер монети."""
    _track(message.chat.id, message)
    parts = message.text.split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else "BTC"
    found = await asyncio.to_thread(search_coin, query)
    if not found:
        m = await message.answer(f"Монету «{query}» не знайдено."); _track(message.chat.id, m)
        return
    coin_id = found[0]
    try:
        await sender(message.chat.id, coin_id)
    except (derivatives.DerivUnavailable, DataUnavailable) as e:
        m = await message.answer(str(e)); _track(message.chat.id, m)
    except Exception as e:
        await _send_error(message.chat.id, e)


@dp.message(Command("deriv"))
async def cmd_deriv(message: Message):
    await _coin_cmd(message, send_deriv)


@dp.message(Command("signals"))
async def cmd_signals(message: Message):
    await _coin_cmd(message, send_confluence)


@dp.message(Command("backtest"))
async def cmd_backtest(message: Message):
    await _coin_cmd(message, send_backtest)


@dp.message(Command("news"))
async def cmd_news(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split(maxsplit=1)
    cur = ""
    if len(parts) > 1:
        found = await asyncio.to_thread(search_coin, parts[1].strip())
        if found:
            cur = found[1]
    try:
        await send_news(message.chat.id, cur)
    except Exception as e:
        await _send_error(message.chat.id, e)


@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    _track(message.chat.id, message)
    if not await _require_pro(message.chat.id, message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        lang = await db.get_lang(message.from_user.id)
        m = await message.answer(t(lang, "ask_hint")); _track(message.chat.id, m)
        return
    answer = await asyncio.to_thread(ai.ask, parts[1].strip())
    m = await message.answer(answer); _track(message.chat.id, m)


@dp.message(Command("portfolio"))
async def cmd_portfolio(message: Message):
    _track(message.chat.id, message)
    await send_portfolio(message.chat.id, message.from_user.id)


@dp.message(Command("addcoin"))
async def cmd_addcoin(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split()
    if len(parts) < 3:
        m = await message.answer("Формат: /addcoin <тикер> <к-сть> [ціна_купівлі]\n"
                                 "Напр.: /addcoin BTC 0.5 60000")
        _track(message.chat.id, m); return
    uid = message.from_user.id
    if not await db.is_pro(uid) and len(await db.list_holdings(uid)) >= 3:
        m = await message.answer("Безкоштовно — до 3 позицій. /upgrade для PRO.")
        _track(message.chat.id, m); return
    found = await asyncio.to_thread(search_coin, parts[1])
    if not found:
        m = await message.answer(f"Монету «{parts[1]}» не знайдено."); _track(message.chat.id, m); return
    try:
        amount = float(parts[2])
        buy = float(parts[3]) if len(parts) > 3 else 0.0
    except ValueError:
        m = await message.answer("Кількість/ціна мають бути числами."); _track(message.chat.id, m); return
    coin_id, symbol, _ = found
    await db.add_holding(uid, coin_id, symbol, amount, buy)
    m = await message.answer(f"✅ Додано: {symbol} × {amount:g} @ {buy:g}")
    _track(message.chat.id, m)
    await send_portfolio(message.chat.id, uid)


@dp.message(Command("delcoin"))
async def cmd_delcoin(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        m = await message.answer("Формат: /delcoin <id> (id з картки портфеля)")
        _track(message.chat.id, m); return
    ok = await db.delete_holding(message.from_user.id, int(parts[1]))
    m = await message.answer("✅ Видалено" if ok else "Позицію не знайдено")
    _track(message.chat.id, m)


@dp.message(Command("alert"))
async def cmd_alert(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split()
    if len(parts) < 5:
        m = await message.answer(
            "Створити алерт:\n/alert <тикер> <тип> <> або <> <значення>\n"
            "Типи: price, pct, rsi, volume\n"
            "Напр.: /alert BTC price > 70000\n"
            "       /alert ETH rsi < 30\n"
            "       /alert SOL pct > 5")
        _track(message.chat.id, m); return
    sym, kind, op, value = parts[1], parts[2].lower(), parts[3], parts[4]
    if kind not in ("price", "pct", "rsi", "volume", "sr_break") or op not in (">", "<"):
        m = await message.answer("Невірний тип або оператор. Тип: price/pct/rsi/volume, оператор: > або <")
        _track(message.chat.id, m); return
    try:
        value = float(value)
    except ValueError:
        m = await message.answer("Значення має бути числом."); _track(message.chat.id, m); return
    ok, msg_text = await alerts.create_alert(message.from_user.id, sym, kind, op, value)
    m = await message.answer(msg_text); _track(message.chat.id, m)


@dp.message(Command("alerts"))
async def cmd_alerts(message: Message):
    _track(message.chat.id, message)
    rules = await db.list_alerts(message.from_user.id)
    if not rules:
        lang = await db.get_lang(message.from_user.id)
        m = await message.answer(t(lang, "no_alerts") + "\nСтворити: /alert BTC price > 70000")
        _track(message.chat.id, m); return
    lines = ["Ваші активні алерти:", ""]
    for r in rules:
        lines.append(f"#{r['id']} {r['symbol']} {r['kind']} {r['op']} {r['value']:g}")
    lines.append("\nВидалити: /delalert <id>")
    m = await message.answer("\n".join(lines)); _track(message.chat.id, m)


@dp.message(Command("delalert"))
async def cmd_delalert(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        m = await message.answer("Формат: /delalert <id>"); _track(message.chat.id, m); return
    ok = await db.delete_alert(message.from_user.id, int(parts[1]))
    m = await message.answer("✅ Видалено" if ok else "Алерт не знайдено")
    _track(message.chat.id, m)


@dp.message(Command("watch"))
async def cmd_watch(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        m = await message.answer("Формат: /watch <тикер>"); _track(message.chat.id, m); return
    found = await asyncio.to_thread(search_coin, parts[1].strip())
    if not found:
        m = await message.answer("Монету не знайдено."); _track(message.chat.id, m); return
    coin_id, symbol, _ = found
    await db.add_watch(message.from_user.id, coin_id, symbol)
    m = await message.answer(f"✅ {symbol} у списку спостереження. /watchlist — переглянути.")
    _track(message.chat.id, m)


@dp.message(Command("watchlist"))
async def cmd_watchlist(message: Message):
    _track(message.chat.id, message)
    items = await db.list_watch(message.from_user.id)
    if not items:
        m = await message.answer("Список спостереження порожній. /watch BTC")
        _track(message.chat.id, m); return
    lines = ["Список спостереження:"] + [f"• {i['symbol']}" for i in items]
    m = await message.answer("\n".join(lines)); _track(message.chat.id, m)


@dp.message(Command("lang"))
async def cmd_lang(message: Message):
    _track(message.chat.id, message)
    parts = message.text.split()
    lang = parts[1].lower() if len(parts) > 1 else ""
    if lang not in ("uk", "en"):
        m = await message.answer("Формат: /lang uk  або  /lang en"); _track(message.chat.id, m); return
    await db.set_lang(message.from_user.id, lang)
    m = await message.answer(t(lang, "lang_set")); _track(message.chat.id, m)


@dp.message(Command("upgrade"))
async def cmd_upgrade(message: Message):
    _track(message.chat.id, message)
    m = await message.answer(payments.pro_summary(), reply_markup=upgrade_keyboard(),
                             parse_mode="Markdown")
    _track(message.chat.id, m)


@dp.message(Command("pro"))
async def cmd_pro(message: Message):
    _track(message.chat.id, message)
    uid = message.from_user.id
    u = await db.ensure_user(uid)
    lang = await db.get_lang(uid)
    if await db.is_pro(uid):
        import datetime
        until = datetime.datetime.fromtimestamp(u["pro_until"]).strftime("%d.%m.%Y")
        refs = await db.count_referrals(uid)
        m = await message.answer(f"{t(lang,'pro_active')} {until}\nЗапрошених друзів: {refs}")
    else:
        m = await message.answer("У вас тариф FREE. /upgrade — отримати PRO.")
    _track(message.chat.id, m)


@dp.callback_query(F.data.startswith("deriv:"))
async def cb_deriv(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    await call.answer("Завантажую деривативи...")
    try:
        await send_deriv(call.message.chat.id, coin_id)
    except derivatives.DerivUnavailable as e:
        m = await call.message.answer(str(e)); _track(call.message.chat.id, m)
    except Exception as e:
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("conf:"))
async def cb_conf(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    await call.answer("Рахую тех.сигнали...")
    try:
        await send_confluence(call.message.chat.id, coin_id)
    except Exception as e:
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("bt:"))
async def cb_bt(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    await call.answer("Запускаю бектест...")
    try:
        await send_backtest(call.message.chat.id, coin_id)
    except Exception as e:
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data.startswith("ai:"))
async def cb_ai(call: CallbackQuery):
    coin_id = call.data.split(":", 1)[1]
    if not await _require_pro(call.message.chat.id, call.from_user.id):
        await call.answer(); return
    await call.answer("AI аналізує...")
    try:
        info = await asyncio.to_thread(get_market_info, coin_id)
        risk_hist = await asyncio.to_thread(get_price_history, coin_id, 30)
        a = full_analysis(info, risk_hist, risk_hist, "30 днів")
        text = await asyncio.to_thread(ai.explain_analysis, a)
        m = await call.message.answer("🤖 " + text); _track(call.message.chat.id, m)
    except Exception as e:
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data == "news")
async def cb_news(call: CallbackQuery):
    await call.answer("Завантажую новини...")
    try:
        await send_news(call.message.chat.id)
    except Exception as e:
        await _send_error(call.message.chat.id, e)


@dp.callback_query(F.data == "portfolio")
async def cb_portfolio(call: CallbackQuery):
    await call.answer()
    await send_portfolio(call.message.chat.id, call.from_user.id)


@dp.callback_query(F.data == "upgrade")
async def cb_upgrade(call: CallbackQuery):
    await call.answer()
    msg = await call.message.answer(payments.pro_summary(),
                                    reply_markup=upgrade_keyboard(), parse_mode="Markdown")
    _track(call.message.chat.id, msg)


@dp.callback_query(F.data == "buy_pro")
async def cb_buy_pro(call: CallbackQuery):
    await call.answer()
    try:
        await payments.send_pro_invoice(bot, call.message.chat.id)
    except Exception as e:
        logging.exception("invoice failed")
        m = await call.message.answer(
            "Не вдалося створити рахунок. Переконайтесь, що оплата зірками "
            "доступна у вашому регіоні.")
        _track(call.message.chat.id, m)


@dp.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: Message):
    if payments.is_pro_payload(message.successful_payment.invoice_payload):
        until = await db.grant_pro(message.from_user.id, settings.PRO_DAYS)
        import datetime
        lang = await db.get_lang(message.from_user.id)
        date = datetime.datetime.fromtimestamp(until).strftime("%d.%m.%Y")
        await message.answer(f"{t(lang,'thanks_pro')} {date}. ⭐")


@dp.message(F.text)
async def on_text(message: Message):
    _track(message.chat.id, message)
    found = await asyncio.to_thread(search_coin, message.text)
    if not found:
        msg = await message.answer(
            "Монету не знайдено. Спробуйте інший тикер або назву.",
            reply_markup=coins_keyboard(),
        )
        _track(message.chat.id, msg)
        return
    coin_id, _, _ = found
    try:
        await send_analysis(message.chat.id, coin_id)
    except Exception as e:
        logging.exception("analysis failed")
        await _send_error(message.chat.id, e)


async def main():
    await db.init()
    logging.info("Фічі: %s", settings.feature_status())
    asyncio.create_task(alerts.watch_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
