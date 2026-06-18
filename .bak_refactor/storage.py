"""
Збереження обраних монет та налаштувань сповіщень.

Дані зберігаються у файлі data/favorites.json поруч із ботом,
тому переживають перезапуск. Структура:

{
  "123456789": {                  # Telegram user_id (він же chat_id у приваті)
    "bitcoin": {
      "symbol": "BTC",
      "name": "Bitcoin",
      "threshold_pct": 2.0,       # поріг зміни ціни для сповіщення, %
      "ref_price": 63500.0        # ціна-орієнтир (оновлюється після сповіщення)
    }
  }
}
"""

import json
import os
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FAVORITES_FILE = os.path.join(DATA_DIR, "favorites.json")

_lock = threading.Lock()


def _load() -> dict:
    """Читає файл обраного. Якщо файлу немає — порожній словник."""
    if not os.path.exists(FAVORITES_FILE):
        return {}
    try:
        with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    """Атомарно записує файл обраного."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = FAVORITES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FAVORITES_FILE)


# ===========================================================================
# Публічні функції
# ===========================================================================

def add_favorite(user_id: int, coin_id: str, symbol: str, name: str,
                 threshold_pct: float, ref_price: float) -> None:
    """Додає монету в обране користувача з порогом сповіщення у %."""
    with _lock:
        data = _load()
        user = data.setdefault(str(user_id), {})
        user[coin_id] = {
            "symbol": symbol,
            "name": name,
            "threshold_pct": float(threshold_pct),
            "ref_price": float(ref_price),
        }
        _save(data)


def remove_favorite(user_id: int, coin_id: str) -> bool:
    """Видаляє монету з обраного. Повертає True, якщо була."""
    with _lock:
        data = _load()
        user = data.get(str(user_id), {})
        if coin_id in user:
            del user[coin_id]
            if not user:
                data.pop(str(user_id), None)
            _save(data)
            return True
        return False


def get_favorites(user_id: int) -> dict:
    """Обрані монети одного користувача: {coin_id: {...}}."""
    with _lock:
        return dict(_load().get(str(user_id), {}))


def all_favorites() -> dict:
    """Усі обрані всіх користувачів (для фонової перевірки цін)."""
    with _lock:
        return _load()


def update_ref_price(user_id: int, coin_id: str, new_price: float) -> None:
    """Оновлює ціну-орієнтир після надісланого сповіщення."""
    with _lock:
        data = _load()
        fav = data.get(str(user_id), {}).get(coin_id)
        if fav:
            fav["ref_price"] = float(new_price)
            _save(data)
