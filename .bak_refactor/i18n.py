"""
БЛОК 7 (частина) — мінімальна локалізація uk/en.

Команда /lang перемикає мову (зберігається у БД). Тут — короткі рядки
інтерфейсу; аналітичні картки лишаються українськими, але UI-підказки
перекладаються.
"""

import settings

STRINGS = {
    "uk": {
        "choose_coin": "Оберіть монету або введіть тикер/назву:",
        "pro_only": "🔒 Ця функція доступна у PRO. Команда /upgrade.",
        "alert_added": "✅ Алерт додано.",
        "alert_limit": "Ліміт безкоштовних алертів вичерпано. /upgrade для PRO.",
        "no_alerts": "У вас немає активних алертів.",
        "lang_set": "✅ Мову змінено: Українська 🇺🇦",
        "ask_hint": "Напишіть питання після /ask, напр.: /ask що таке RSI?",
        "portfolio_empty": "Портфель порожній. Додайте: /addcoin BTC 0.5 60000",
        "pro_active": "✅ PRO активний до",
        "thanks_pro": "🎉 Дякуємо! PRO активовано до",
    },
    "en": {
        "choose_coin": "Choose a coin or type a ticker/name:",
        "pro_only": "🔒 This feature is PRO-only. Use /upgrade.",
        "alert_added": "✅ Alert added.",
        "alert_limit": "Free alert limit reached. Use /upgrade for PRO.",
        "no_alerts": "You have no active alerts.",
        "lang_set": "✅ Language set: English 🇬🇧",
        "ask_hint": "Type a question after /ask, e.g.: /ask what is RSI?",
        "portfolio_empty": "Portfolio is empty. Add: /addcoin BTC 0.5 60000",
        "pro_active": "✅ PRO active until",
        "thanks_pro": "🎉 Thank you! PRO activated until",
    },
}


def t(lang: str, key: str) -> str:
    lang = lang if lang in STRINGS else settings.DEFAULT_LANG
    return STRINGS.get(lang, STRINGS["uk"]).get(key, STRINGS["uk"].get(key, key))
