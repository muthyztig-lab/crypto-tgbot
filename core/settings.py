import os


def _load_dotenv() -> None:
    """Мінімальний парсер .env (без зовнішніх залежностей)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _flag(key: str, default: bool = False) -> bool:
    v = _get(key, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


BOT_TOKEN = _get("BOT_TOKEN")

OPENAI_API_KEY = _get("OPENAI_API_KEY")
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-4o-mini")
CRYPTOPANIC_API_KEY = _get("CRYPTOPANIC_API_KEY")

SENTRY_DSN = _get("SENTRY_DSN")
REDIS_URL = _get("REDIS_URL")

PRO_PRICE_STARS = int(_get("PRO_PRICE_STARS", "299") or "299")
PRO_DAYS = int(_get("PRO_DAYS", "30") or "30")
PAYMENT_PROVIDER_TOKEN = _get("PAYMENT_PROVIDER_TOKEN")

RATE_WINDOW_SEC = int(_get("RATE_WINDOW_SEC", "60") or "60")
RATE_FREE_MAX = int(_get("RATE_FREE_MAX", "20") or "20")
RATE_PRO_MAX = int(_get("RATE_PRO_MAX", "120") or "120")

ALERTS_FREE_MAX = int(_get("ALERTS_FREE_MAX", "3") or "3")
ALERTS_PRO_MAX = int(_get("ALERTS_PRO_MAX", "100") or "100")

DEFAULT_LANG = _get("DEFAULT_LANG", "uk")

ENABLE_REALTIME_WS = _flag("ENABLE_REALTIME_WS", False)

# ───────────────────────── Алго-торгівля (R&D) ─────────────────────────
TRADE_MODE = _get("TRADE_MODE", "paper").lower()          # paper | live
BINANCE_API_KEY = _get("BINANCE_API_KEY")
BINANCE_API_SECRET = _get("BINANCE_API_SECRET")
BINANCE_TESTNET = _flag("BINANCE_TESTNET", True)

FEE_BPS = float(_get("FEE_BPS", "10") or "10")
SLIPPAGE_BPS = float(_get("SLIPPAGE_BPS", "5") or "5")
EXEC_LATENCY_BARS = int(_get("EXEC_LATENCY_BARS", "1") or "1")

START_EQUITY = float(_get("START_EQUITY", "1000") or "1000")
POLL_SECONDS = int(_get("POLL_SECONDS", "20") or "20")

ADMIN_IDS = [
    int(x) for x in _get("ADMIN_IDS").replace(";", ",").split(",") if x.strip().isdigit()
]


def is_admin(user_id: int) -> bool:
    """Порожній ADMIN_IDS = торгівля дозволена всім (зручно для демо)."""
    return not ADMIN_IDS or user_id in ADMIN_IDS


def can_trade_live() -> bool:
    """live-режим доступний лише коли задані ключі біржі."""
    return TRADE_MODE == "live" and bool(BINANCE_API_KEY and BINANCE_API_SECRET)


def feature_status() -> dict:
    """Зведення, які фічі ввімкнені (для /admin або логів)."""
    return {
        "ai": bool(OPENAI_API_KEY),
        "news": True,
        "cryptopanic": bool(CRYPTOPANIC_API_KEY),
        "sentry": bool(SENTRY_DSN),
        "redis": bool(REDIS_URL),
        "payments_stars": True,
        "payments_card": bool(PAYMENT_PROVIDER_TOKEN),
        "realtime_ws": ENABLE_REALTIME_WS,
        "trade_mode": TRADE_MODE,
        "binance_testnet": BINANCE_TESTNET,
        "binance_keys": bool(BINANCE_API_KEY and BINANCE_API_SECRET),
    }
