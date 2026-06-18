"""
БЛОК 5 (частина) — AI-помічник (опційно, потребує OPENAI_API_KEY).

Якщо ключа немає — функції повертають зрозуміле повідомлення, а бот
продовжує працювати без AI. Якщо ключ заданий — відповідає на питання про
крипту українською та коротко пояснює аналіз монети природною мовою.

Жодних фінансових порад — лише пояснення даних. Це закладено в системний
промпт.
"""

import logging
import settings

SYSTEM = (
    "Ти — асистент крипто-бота. Відповідай українською, стисло й по суті. "
    "Пояснюй ринкові дані та індикатори простою мовою. Не давай прямих "
    "фінансових порад («купуй/продавай») — лише пояснюй ризики й факти. "
    "Завжди нагадуй, що це не інвестиційна рекомендація, якщо доречно."
)


def available() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _client():
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat(messages, max_tokens=500) -> str:
    if not available():
        return ("🔒 AI-помічник вимкнено. Додайте OPENAI_API_KEY у .env, "
                "щоб увімкнути відповіді на питання та AI-пояснення.")
    try:
        resp = _client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logging.exception("OpenAI помилка")
        return f"⚠️ AI тимчасово недоступний ({type(e).__name__})."


def ask(question: str, context: str = "") -> str:
    """Вільне питання користувача про крипту."""
    msgs = [{"role": "system", "content": SYSTEM}]
    if context:
        msgs.append({"role": "system", "content": f"Контекст даних:\n{context}"})
    msgs.append({"role": "user", "content": question})
    return _chat(msgs)


def explain_analysis(a: dict) -> str:
    """Коротке AI-пояснення картки аналізу монети."""
    info = a.get("info", {})
    ctx = (
        f"Монета: {info.get('name')} ({info.get('symbol')})\n"
        f"Ціна: ${info.get('price')}\n"
        f"Зміна 24г: {info.get('change_24h_pct')}%\n"
        f"Ризик-бал: {a.get('risk_score')} ({a.get('risk_category')})\n"
        f"Волатильність: {a.get('volatility_pct')}%\n"
        f"RSI: {a.get('rsi')}, тренд: {a.get('trend')}, "
        f"просадка: {a.get('max_drawdown_pct')}%"
    )
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content":
            "Поясни простими словами стан цієї монети та її ризики "
            "(3-4 речення):\n" + ctx},
    ]
    return _chat(msgs, max_tokens=300)
