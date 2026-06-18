"""
Отримання ринкових даних БЕЗ API-ключів.

Джерела (усі публічні, жодних ключів):
- CoinGecko public API — ціни, історія, OHLC, огляд ринку, топ руху
- OKX public API      — хвилинні свічки (1хв/5хв/15хв), бо безкоштовний
                        CoinGecko дає мінімум 5-хвилинні точки
- alternative.me      — Fear & Greed Index

Жодних Binance API та ключів не використовується.

Можливості:
- пошук монети за тикером або назвою
- поточна ринкова інформація (ціна, капіталізація, обсяг, зміна за 24г)
- історія цін за будь-який таймфрейм від 1 хвилини до 1 року
- OHLC-свічки для свічкового графіка НА ВСІХ таймфреймах
- глобальний огляд ринку (капіталізація, домінація BTC/ETH)
- топ зростання / падіння за 24 години
- пакетне отримання цін (для системи сповіщень)
"""

import time
import requests

COINGECKO = "https://api.coingecko.com/api/v3"
OKX = "https://www.okx.com/api/v5"
FEAR_GREED = "https://api.alternative.me/fng/"

HEADERS = {"User-Agent": "CryptoRiskBot/3.0"}


class DataUnavailable(Exception):
    """Дані для монети/таймфрейму недоступні (зрозуміле повідомлення для чату)."""

# ---------------------------------------------------------------------------
# Популярні монети: тикер -> coingecko id (кнопки головного меню)
# ---------------------------------------------------------------------------
POPULAR_COINS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "TON": "the-open-network",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "TRX": "tron",
    "LTC": "litecoin",
}

# ---------------------------------------------------------------------------
# Таймфрейми графіка: ключ callback -> налаштування
#
#   label / short — підписи для картки та кнопок
#   line          — джерело лінійного графіка:
#                     ("okx", bar, limit, group)  — свічки OKX, лінія по close
#                     ("gecko", days, slice_min)  — CoinGecko market_chart
#   candle        — джерело свічок:
#                     ("okx", bar, limit, group)  — bar-свічки OKX,
#                       group > 1 — об'єднуємо кожні N свічок в одну
#                     ("gecko_ohlc", days, None)  — CoinGecko /ohlc
#
# Чому два джерела:
#   CoinGecko (безкоштовний) дає мінімум 5-хвилинні точки та свічки від 30 хв,
#   тому хвилинні таймфрейми та свічки 1хв-4г беремо з публічного API біржі
#   OKX (теж БЕЗ ключів). CoinGecko лишається для 1д..1р та всієї аналітики.
# ---------------------------------------------------------------------------
TIMEFRAMES = {
    # Короткі таймфрейми — це інтервали свічок (як на TradingView/Binance):
    # кожна кнопка тягне ВЛАСНИЙ нативний бар OKX і показує ~60-90 свічок.
    # Раніше 1х/5х будувалися з 1-секундних свічок OKX, де в більшості секунд
    # немає угод (open=high=low=close) -> графік виходив «пласким» і ламався.
    "1m":   {"label": "1-хв свічки",  "short": "1х",  "line": ("okx", "1m", 60, 1),    "candle": ("okx", "1m", 60, 1)},
    "5m":   {"label": "5-хв свічки",  "short": "5х",  "line": ("okx", "5m", 72, 1),    "candle": ("okx", "5m", 72, 1)},
    "15m":  {"label": "15-хв свічки", "short": "15х", "line": ("okx", "15m", 80, 1),   "candle": ("okx", "15m", 80, 1)},
    "1h":   {"label": "1-год свічки", "short": "1г",  "line": ("okx", "1H", 96, 1),    "candle": ("okx", "1H", 96, 1)},
    "4h":   {"label": "4-год свічки", "short": "4г",  "line": ("okx", "4H", 90, 1),    "candle": ("okx", "4H", 90, 1)},
    "1d":   {"label": "24 години",  "short": "1д",  "line": ("gecko", 1, None),      "candle": ("gecko_ohlc", 1, None)},
    "7d":   {"label": "7 днів",     "short": "1т",  "line": ("gecko", 7, None),      "candle": ("gecko_ohlc", 7, None)},
    "30d":  {"label": "30 днів",    "short": "1м",  "line": ("gecko", 30, None),     "candle": ("gecko_ohlc", 30, None)},
    "90d":  {"label": "3 місяці",   "short": "3м",  "line": ("gecko", 90, None),     "candle": ("gecko_ohlc", 90, None)},
    "180d": {"label": "6 місяців",  "short": "6м",  "line": ("gecko", 180, None),    "candle": ("gecko_ohlc", 180, None)},
    "365d": {"label": "1 рік",      "short": "1р",  "line": ("gecko", 365, None),    "candle": ("gecko_ohlc", 365, None)},
}
DEFAULT_TIMEFRAME = "30d"

# Порядок кнопок таймфреймів у клавіатурі (два ряди, щоб вмістились)
TIMEFRAME_ROWS = [
    ["1m", "5m", "15m", "1h", "4h", "1d"],
    ["7d", "30d", "90d", "180d", "365d"],
]

# ---------------------------------------------------------------------------
# Простий кеш у пам'яті, щоб не впиратися в ліміти безкоштовного API
# ---------------------------------------------------------------------------
_cache = {}
CACHE_TTL = 60     # секунд
CACHE_MAX = 500    # максимум записів у кеші (захист від зростання памʼяті)


def _get(url, params=None, timeout=15, retries=3):
    """
    HTTP GET із перевіркою статусу.
    Безкоштовне API CoinGecko має ліміт запитів — при відповіді 429
    робимо паузу та повторюємо запит (до `retries` разів).
    """
    for attempt in range(retries + 1):
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code == 429:
            if attempt < retries:
                time.sleep(5 * (attempt + 1))  # 5, 10, 15 секунд
                continue
            # Усі спроби вичерпано через ліміт запитів — зрозуміле повідомлення
            # замість сирого HTTPError 429.
            raise DataUnavailable(
                "Сервіс даних тимчасово перевантажений (ліміт запитів). "
                "Спробуйте за хвилину."
            )
        r.raise_for_status()
        return r.json()


def _prune_cache(now: float) -> None:
    """Прибирає протерміновані записи; якщо все одно завелико — найстаріші."""
    expired = [k for k, (ts, _) in _cache.items() if now - ts >= CACHE_TTL]
    for k in expired:
        _cache.pop(k, None)
    if len(_cache) > CACHE_MAX:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[: len(_cache) - CACHE_MAX]:
            _cache.pop(k, None)


def _cached(key, fn, ttl=CACHE_TTL):
    """Повертає значення з кешу або обчислює та зберігає його."""
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    value = fn()
    _cache[key] = (now, value)
    if len(_cache) > CACHE_MAX:
        _prune_cache(now)
    return value


# ===========================================================================
# Пошук та базова інформація
# ===========================================================================

def search_coin(query: str):
    """Пошук монети за тикером або назвою. Повертає (id, symbol, name) або None."""
    q = query.strip().upper()
    if q in POPULAR_COINS:
        return POPULAR_COINS[q], q, q
    try:
        data = _get(f"{COINGECKO}/search", {"query": query})
        coins = data.get("coins", [])
        if not coins:
            return None
        c = coins[0]
        return c["id"], c["symbol"].upper(), c["name"]
    except Exception:
        return None


def get_market_info(coin_id: str) -> dict:
    """Поточна ціна, капіталізація, обсяг, зміна за 24 години."""
    def fetch():
        data = _get(
            f"{COINGECKO}/coins/markets",
            {"vs_currency": "usd", "ids": coin_id},
        )
        if not data:
            raise ValueError(f"Монету не знайдено: {coin_id}")
        d = data[0]
        return {
            "id": d["id"],
            "symbol": d["symbol"].upper(),
            "name": d["name"],
            "price": d["current_price"],
            "market_cap": d["market_cap"],
            "volume_24h": d["total_volume"],
            "change_24h_pct": d.get("price_change_percentage_24h") or 0.0,
            "high_24h": d.get("high_24h"),
            "low_24h": d.get("low_24h"),
            "rank": d.get("market_cap_rank"),
        }

    return _cached(f"info:{coin_id}", fetch)


# ===========================================================================
# Історія цін та свічки
# ===========================================================================

def get_price_history(coin_id: str, days: int = 30) -> list:
    """Історія цін: list of [timestamp_ms, price]."""
    def fetch():
        data = _get(
            f"{COINGECKO}/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": days},
        )
        return data["prices"]

    return _cached(f"hist:{coin_id}:{days}", fetch)


def get_okx_candles(symbol: str, bar: str, limit: int, group: int = 1) -> list:
    """
    Свічки з публічного API біржі OKX (без ключів):
    list of [timestamp_ms, open, high, low, close], від старих до нових.

    bar: "1s", "1m", "5m", ... ; limit: до 300 свічок.
    group > 1 — об'єднуємо кожні N свічок в одну (для довших періодів).
    Якщо пари {SYMBOL}-USDT на біржі немає — DataUnavailable.
    """
    inst = f"{symbol.upper()}-USDT"

    def fetch():
        d = _get(f"{OKX}/market/candles", {"instId": inst, "bar": bar, "limit": limit})
        rows = d.get("data") or []
        if d.get("code") != "0" or len(rows) < 3:
            raise DataUnavailable(
                f"Хвилинні дані для {symbol.upper()} недоступні "
                f"(немає пари {inst} на біржі). Оберіть таймфрейм від 1Д."
            )
        # OKX повертає від нових до старих -> розвертаємо
        out = [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])]
            for r in reversed(rows)
        ]
        return _group_candles(out, group)

    # короткий кеш — хвилинні дані швидко застарівають
    return _cached(f"okx:{inst}:{bar}:{limit}:{group}", fetch, ttl=10)


def _group_candles(rows: list, group: int) -> list:
    """Об'єднує кожні `group` свічок в одну (open першої, close останньої)."""
    if group <= 1:
        return rows
    out = []
    for i in range(0, len(rows) - group + 1, group):
        chunk = rows[i : i + group]
        out.append([
            chunk[0][0],
            chunk[0][1],
            max(c[2] for c in chunk),
            min(c[3] for c in chunk),
            chunk[-1][4],
        ])
    return out


def get_history_for_timeframe(coin_id: str, tf_key: str, symbol: str) -> list:
    """
    Дані лінійного графіка для таймфрейму (1 хвилина .. 1 рік):
    list of [timestamp_ms, price].

    1хв/5хв/15хв — свічки OKX (лінія по цінах close),
    1г/4г        — добові 5-хвилинні дані CoinGecko, лишаємо "хвіст",
    1д..1р       — CoinGecko market_chart.
    """
    tf = TIMEFRAMES.get(tf_key, TIMEFRAMES[DEFAULT_TIMEFRAME])
    src = tf["line"]
    if src[0] == "okx":
        candles = get_okx_candles(symbol, src[1], src[2], src[3])
        return [[c[0], c[4]] for c in candles]

    _, days, slice_minutes = src
    history = get_price_history(coin_id, days)
    if slice_minutes:
        cutoff_ms = (time.time() - slice_minutes * 60) * 1000
        sliced = [p for p in history if p[0] >= cutoff_ms]
        if len(sliced) >= 3:  # захист, якщо даних замало
            return sliced
    return history


def get_candles_for_timeframe(coin_id: str, tf_key: str, symbol: str) -> list:
    """
    OHLC-свічки для таймфрейму — ДЛЯ ВСІХ періодів від 1 хвилини:
    list of [timestamp_ms, open, high, low, close].

    1хв..4г — свічки OKX, 1д..1р — CoinGecko /ohlc
    (деталізація: 1д -> 30-хв свічки, 7-30д -> 4-год, далі -> 4-денні).
    """
    tf = TIMEFRAMES.get(tf_key, TIMEFRAMES[DEFAULT_TIMEFRAME])
    src = tf["candle"]
    if src[0] == "okx":
        return get_okx_candles(symbol, src[1], src[2], src[3])

    valid = [1, 7, 14, 30, 90, 180, 365]
    days = min(valid, key=lambda v: abs(v - src[1]))

    def fetch():
        return _get(
            f"{COINGECKO}/coins/{coin_id}/ohlc",
            {"vs_currency": "usd", "days": days},
        )

    return _cached(f"ohlc:{coin_id}:{days}", fetch)


# ===========================================================================
# Огляд ринку, топ руху, Fear & Greed
# ===========================================================================

def get_global_overview() -> dict:
    """Глобальний стан крипторинку."""
    def fetch():
        d = _get(f"{COINGECKO}/global")["data"]
        return {
            "total_mcap_usd": d["total_market_cap"]["usd"],
            "total_volume_usd": d["total_volume"]["usd"],
            "mcap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd") or 0.0,
            "btc_dominance_pct": d["market_cap_percentage"].get("btc", 0.0),
            "eth_dominance_pct": d["market_cap_percentage"].get("eth", 0.0),
            "active_coins": d.get("active_cryptocurrencies", 0),
        }

    return _cached("global", fetch, ttl=120)


def get_top_movers(limit: int = 5):
    """
    Топ зростання та падіння за 24г серед 100 найбільших монет.
    Повертає (gainers, losers) — списки словників.
    """
    def fetch():
        data = _get(
            f"{COINGECKO}/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 100,
                "page": 1,
            },
        )
        rows = [
            {
                "symbol": d["symbol"].upper(),
                "name": d["name"],
                "price": d["current_price"],
                "change_24h_pct": d.get("price_change_percentage_24h") or 0.0,
            }
            for d in data
            if d.get("current_price") is not None
            # відсікаємо токени з не-латинськими назвами (не відмалюються)
            and d["symbol"].isascii() and d["name"].isascii()
        ]
        rows.sort(key=lambda x: x["change_24h_pct"], reverse=True)
        return rows

    rows = _cached("movers", fetch, ttl=120)
    return rows[:limit], rows[-limit:][::-1]


def get_fear_greed() -> dict:
    """Crypto Fear & Greed Index (alternative.me, без ключа). 0=страх, 100=жадібність."""
    def fetch():
        d = _get(FEAR_GREED, {"limit": 1})["data"][0]
        value = int(d["value"])
        labels_ua = {
            "Extreme Fear": "Сильний страх",
            "Fear": "Страх",
            "Neutral": "Нейтрально",
            "Greed": "Жадібність",
            "Extreme Greed": "Сильна жадібність",
        }
        return {
            "value": value,
            "label": labels_ua.get(d.get("value_classification", ""), "Нейтрально"),
        }

    try:
        return _cached("fng", fetch, ttl=600)
    except Exception:
        return {"value": 50, "label": "недоступно"}


# ===========================================================================
# Пакетні ціни (для фонової перевірки сповіщень)
# ===========================================================================

def get_simple_prices(coin_ids: list) -> dict:
    """
    Поточні ціни одним запитом: {coin_id: price}.
    Використовується системою сповіщень, щоб не робити запит на кожну монету.
    """
    if not coin_ids:
        return {}
    data = _get(
        f"{COINGECKO}/simple/price",
        {"ids": ",".join(sorted(set(coin_ids))), "vs_currencies": "usd"},
    )
    return {cid: v["usd"] for cid, v in data.items() if "usd" in v}
