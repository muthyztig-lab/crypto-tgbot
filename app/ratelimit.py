import time
import logging
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from core import settings

_hits: dict = {}


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.time()
        window = settings.RATE_WINDOW_SEC
        dq = _hits.setdefault(user.id, deque())
        while dq and now - dq[0] > window:
            dq.popleft()

        if len(dq) >= settings.RATE_MAX:
            wait = int(window - (now - dq[0])) + 1
            text = f"⏳ Забагато запитів. Спробуйте за {wait} с."
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=False)
                elif isinstance(event, Message):
                    await event.answer(text)
            except Exception:
                logging.debug("rate-limit notice failed")
            return

        dq.append(now)
        return await handler(event, data)
