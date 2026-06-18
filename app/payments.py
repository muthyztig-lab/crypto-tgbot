from aiogram import Bot
from aiogram.types import LabeledPrice

from core import settings

PRO_PAYLOAD = "pro_subscription"


def pro_payload() -> str:
    return PRO_PAYLOAD


def is_pro_payload(payload: str) -> bool:
    return payload == PRO_PAYLOAD


async def send_pro_invoice(bot: Bot, chat_id: int) -> None:
    """Надсилає інвойс на Pro за Telegram Stars."""
    price = settings.PRO_PRICE_STARS
    days = settings.PRO_DAYS
    await bot.send_invoice(
        chat_id=chat_id,
        title="Crypto Risk Bot PRO",
        description=(
            f"PRO на {days} днів: необмежені алерти, AI-пояснення, "
            f"деривативи, бектести, портфель без лімітів і пріоритетна швидкість."
        ),
        payload=PRO_PAYLOAD,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"PRO {days} днів", amount=price)],
        start_parameter="pro",
    )


def pro_summary() -> str:
    """Текст для команди /upgrade."""
    return (
        f"⭐ *PRO-підписка* — {settings.PRO_PRICE_STARS} Stars / "
        f"{settings.PRO_DAYS} днів\n\n"
        "Що дає PRO:\n"
        f"• Необмежені алерти (free: {settings.ALERTS_FREE_MAX})\n"
        "• AI-пояснення та запитання (/ask)\n"
        "• Деривативи, конфлюенс-сигнали, бектести\n"
        "• Портфель без лімітів\n"
        "• Пріоритетна швидкість (вищі ліміти запитів)\n\n"
        "Натисніть кнопку нижче, щоб оплатити зірками Telegram."
    )
