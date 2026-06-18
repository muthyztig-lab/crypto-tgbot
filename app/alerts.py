import asyncio
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile

from core import storage
from core import db
from core import settings
from analytics.analysis import updated_at, rsi
from sources.market_data import get_simple_prices, get_market_info, get_price_history, search_coin
from render.svg_render import build_alert_svg, svg_to_png_bytes

CHECK_INTERVAL = 30


async def _check_favorites(bot: Bot) -> None:
    favorites = storage.all_favorites()
    if not favorites:
        return
    coin_ids = [cid for user in favorites.values() for cid in user.keys()]
    prices = await asyncio.to_thread(get_simple_prices, coin_ids)

    for user_id_str, coins in favorites.items():
        user_id = int(user_id_str)
        for coin_id, fav in coins.items():
            current = prices.get(coin_id)
            ref = fav.get("ref_price")
            if not current or not ref:
                continue
            change_pct = (current - ref) / ref * 100.0
            if abs(change_pct) < fav["threshold_pct"]:
                continue
            try:
                png = svg_to_png_bytes(build_alert_svg(
                    symbol=fav["symbol"], name=fav["name"], ref_price=ref,
                    current_price=current, change_pct=change_pct,
                    threshold_pct=fav["threshold_pct"], time_str=updated_at()))
                await bot.send_photo(
                    chat_id=user_id,
                    photo=BufferedInputFile(png, filename=f"{fav['symbol']}_alert.png"),
                    caption=(f"Сповіщення: {fav['name']} ({fav['symbol']}) "
                             f"{change_pct:+.2f}% (поріг {fav['threshold_pct']}%)"))
                storage.update_ref_price(user_id, coin_id, current)
            except Exception:
                logging.exception("Не вдалося надіслати сповіщення %s -> %s", coin_id, user_id)


def _fired(kind: str, op: str, value: float, *, price=None, change_pct=None,
           rsi_val=None, volume=None) -> bool:
    def cmp(x):
        return x > value if op == ">" else x < value
    if kind in ("price", "sr_break") and price is not None:
        return cmp(price)
    if kind == "pct" and change_pct is not None:
        return abs(change_pct) >= value
    if kind == "rsi" and rsi_val is not None:
        return cmp(rsi_val)
    if kind == "volume" and volume is not None:
        return cmp(volume)
    return False


async def _check_rules(bot: Bot) -> None:
    rules = await db.all_active_alerts()
    if not rules:
        return
    coin_ids = list({r["coin_id"] for r in rules})
    prices = await asyncio.to_thread(get_simple_prices, coin_ids)

    for r in rules:
        price = prices.get(r["coin_id"])
        if price is None:
            continue
        kind = r["kind"]
        change_pct = ((price - r["ref_price"]) / r["ref_price"] * 100.0) if r["ref_price"] else 0.0
        rsi_val = volume = None
        try:
            if kind == "rsi":
                hist = await asyncio.to_thread(get_price_history, r["coin_id"], 30)
                rsi_val = rsi([p[1] for p in hist])
            elif kind == "volume":
                info = await asyncio.to_thread(get_market_info, r["coin_id"])
                volume = info.get("volume_24h")
        except Exception:
            continue

        if not _fired(kind, r["op"], r["value"], price=price, change_pct=change_pct,
                      rsi_val=rsi_val, volume=volume):
            continue

        human = {
            "price": f"ціна {r['op']} {r['value']:g}",
            "sr_break": f"пробій рівня {r['op']} {r['value']:g}",
            "pct": f"зміна ±{r['value']:g}%",
            "rsi": f"RSI {r['op']} {r['value']:g}",
            "volume": f"обсяг 24г {r['op']} {r['value']:g}",
        }.get(kind, kind)
        try:
            await bot.send_message(
                chat_id=r["user_id"],
                text=(f"🔔 Алерт {r['symbol']}: {human} спрацював.\n"
                      f"Поточна ціна: {price}"))
            if kind == "pct":
                await db.deactivate_alert(r["id"])
            else:
                await db.deactivate_alert(r["id"])
        except Exception:
            logging.exception("Не вдалося надіслати алерт-правило %s", r["id"])


async def watch_loop(bot: Bot) -> None:
    logging.info("Систему сповіщень запущено (інтервал %s с, realtime=%s)",
                 CHECK_INTERVAL, settings.ENABLE_REALTIME_WS)
    while True:
        try:
            await _check_favorites(bot)
        except Exception:
            logging.exception("Помилка циклу обраного")
        try:
            await _check_rules(bot)
        except Exception:
            logging.exception("Помилка циклу правил")
        await asyncio.sleep(CHECK_INTERVAL)


_check_once = _check_favorites


async def create_alert(user_id: int, query: str, kind: str, op: str, value: float):
    """Знаходить монету за тикером і додає алерт. Повертає (ok, msg)."""
    found = await asyncio.to_thread(search_coin, query)
    if not found:
        return False, f"Монету «{query}» не знайдено."
    coin_id, symbol, _ = found
    limit = settings.ALERTS_PRO_MAX if await db.is_pro(user_id) else settings.ALERTS_FREE_MAX
    if await db.count_alerts(user_id) >= limit:
        return False, (f"Ліміт алертів вичерпано ({limit}). /upgrade для PRO.")
    ref = 0.0
    try:
        ref = (await asyncio.to_thread(get_market_info, coin_id)).get("price") or 0.0
    except Exception:
        pass
    await db.add_alert(user_id, coin_id, symbol, kind, op, value, ref)
    return True, f"✅ Алерт додано: {symbol} {kind} {op} {value:g}"
