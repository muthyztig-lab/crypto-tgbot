import json
import os
import threading

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
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
