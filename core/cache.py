import json
import time
import logging

from core import settings

_mem: dict = {}
_MEM_MAX = 1000

_redis = None
if settings.REDIS_URL:
    try:
        import redis  # type: ignore

        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis.ping()
        logging.info("Redis-кеш підключено")
    except Exception:
        logging.warning("REDIS_URL заданий, але Redis недоступний — кеш у пам'яті")
        _redis = None


def get(key: str):
    """Повертає значення з кешу або None."""
    if _redis is not None:
        try:
            raw = _redis.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception:
            pass
    item = _mem.get(key)
    if not item:
        return None
    expires, value = item
    if expires and time.time() > expires:
        _mem.pop(key, None)
        return None
    return value


def set(key: str, value, ttl: int = 60) -> None:
    """Зберігає значення з TTL у секундах."""
    if _redis is not None:
        try:
            _redis.set(key, json.dumps(value), ex=ttl)
            return
        except Exception:
            pass
    if len(_mem) > _MEM_MAX:
        oldest = min(_mem, key=lambda k: _mem[k][0] or 0)
        _mem.pop(oldest, None)
    _mem[key] = (time.time() + ttl if ttl else 0, value)


def cached(key: str, fn, ttl: int = 60):
    """get-or-compute хелпер."""
    val = get(key)
    if val is not None:
        return val
    val = fn()
    set(key, val, ttl)
    return val
