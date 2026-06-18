"""
БЛОК 7 (частина) — пер-юзер обмеження частоти (anti-spam / захист API).

aiogram-middleware: рахує важкі запити в ковзному вікні. Free та PRO мають
різні ліміти (settings.RATE_FREE_MAX / RATE_PRO_MAX). При перевищенні —
ввічливо просить зачекати й не виконує хендлер.

PRO-перевірка робиться через db.is_pro (кешується коротко, щоб не бити БД).
"""

import time
import logging
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

import settings
import db

_hits: dict = {}            # user_id -> deque[timestamps]
_pro_cache: dict = {}       # user_id -> (expires, is_pro)
_PRO_TTL = 30


async def _is_pro(user_id: int) -> bool:
    now = time.time()
    item = _pro_cache.get(user_id)
    if item and item[0] > now:
        return item[1]
    try:
        val = await db.is_pro(user_id)
    except Exception:
        val = False
    _pro_cache[user_id] = (now + _PRO_TTL, val)
    return val


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        uid = user.id
        now = time.time()
        window = settings.RATE_WINDOW_SEC
        dq = _hits.setdefault(uid, deque())
        while dq and now - dq[0] > window:
            dq.popleft()

        limit = settings.RATE_PRO_MAX if await _is_pro(uid) else settings.RATE_FREE_MAX
        if len(dq) >= limit:
            wait = int(window - (now - dq[0])) + 1
            text = f"⏳ Забагато запитів. Спробуйте за {wait} с (або /upgrade для вищих лімітів)."
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=False)
                elif isinstance(event, Message):
                    await event.answer(text)
            except Exception:
                logging.debug("rate-limit notice failed")
            return  # хендлер НЕ виконується
        dq.append(now)
        return await handler(event, data)
