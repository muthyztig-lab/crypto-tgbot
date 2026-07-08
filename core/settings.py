import os


def _load_dotenv() -> None:
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
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _flag(key: str, default: bool = False) -> bool:
    return _get(key, "1" if default else "0").lower() in ("1", "true", "yes", "on")


BOT_TOKEN = _get("BOT_TOKEN")
SENTRY_DSN = _get("SENTRY_DSN")

RATE_WINDOW_SEC = int(_get("RATE_WINDOW_SEC", "60") or "60")
RATE_MAX = int(_get("RATE_FREE_MAX", "60") or "60")

TRADE_MODE = _get("TRADE_MODE", "paper").lower()
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
    return not ADMIN_IDS or user_id in ADMIN_IDS


def can_trade_live() -> bool:
    return TRADE_MODE == "live" and bool(BINANCE_API_KEY and BINANCE_API_SECRET)


def feature_status() -> dict:
    return {
        "trade_mode": TRADE_MODE,
        "binance_testnet": BINANCE_TESTNET,
        "binance_keys": bool(BINANCE_API_KEY and BINANCE_API_SECRET),
        "sentry": bool(SENTRY_DSN),
    }
