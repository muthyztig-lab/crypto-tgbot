"""
База даних (SQLite через aiosqlite) — замість JSON-файлу.

Зберігає користувачів і тарифи, алерти-правила, watchlist та портфель.
Асинхронна, безпечна для конкурентного доступу. Файл data/bot.db.

Таблиці:
- users      — профіль, мова, тариф (free/pro), pro_until, реферер
- alerts     — правила сповіщень (ціна/%/RSI/пробій рівня/обсяг)
- watchlist  — список спостереження
- holdings   — позиції портфеля (монета, к-сть, ціна купівлі)
- signals    — журнал згенерованих сигналів (для трекінгу точності)
"""

import os
import time
import aiosqlite

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    lang        TEXT    DEFAULT 'uk',
    tier        TEXT    DEFAULT 'free',
    pro_until   INTEGER DEFAULT 0,
    referrer_id INTEGER DEFAULT 0,
    created_at  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    coin_id     TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    kind        TEXT    NOT NULL,          -- price | pct | rsi | sr_break | volume
    op          TEXT    DEFAULT '>',       -- > | <
    value       REAL    NOT NULL,
    ref_price   REAL    DEFAULT 0,
    active      INTEGER DEFAULT 1,
    created_at  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id INTEGER NOT NULL,
    coin_id TEXT    NOT NULL,
    symbol  TEXT    NOT NULL,
    PRIMARY KEY (user_id, coin_id)
);
CREATE TABLE IF NOT EXISTS holdings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    coin_id    TEXT    NOT NULL,
    symbol     TEXT    NOT NULL,
    amount     REAL    NOT NULL,
    buy_price  REAL    DEFAULT 0,
    created_at INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS signals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    coin_id    TEXT,
    symbol     TEXT,
    direction  TEXT,
    entry      REAL,
    stop_loss  REAL,
    take_profit REAL,
    created_at INTEGER
);
"""


async def init() -> None:
    """Створює файл БД та таблиці, якщо їх немає."""
    os.makedirs(DATA_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


# ---------------------------------------------------------------------------
# Користувачі та тарифи
# ---------------------------------------------------------------------------

async def ensure_user(user_id: int, referrer_id: int = 0) -> dict:
    """Повертає користувача, створюючи його за потреби."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users(user_id, referrer_id, created_at) VALUES(?,?,?)",
                (user_id, referrer_id, int(time.time())),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row)


async def get_tier(user_id: int) -> str:
    """Актуальний тариф: 'pro', якщо підписка ще діє, інакше 'free'."""
    u = await ensure_user(user_id)
    if u["tier"] == "pro" and u["pro_until"] > time.time():
        return "pro"
    return "free"


async def is_pro(user_id: int) -> bool:
    return await get_tier(user_id) == "pro"


async def grant_pro(user_id: int, days: int) -> int:
    """Активує/продовжує Pro на N днів. Повертає новий pro_until (epoch)."""
    u = await ensure_user(user_id)
    base = max(u["pro_until"], int(time.time()))
    new_until = base + days * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET tier='pro', pro_until=? WHERE user_id=?",
            (new_until, user_id),
        )
        await db.commit()
    return new_until


async def set_lang(user_id: int, lang: str) -> None:
    await ensure_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
        await db.commit()


async def get_lang(user_id: int) -> str:
    u = await ensure_user(user_id)
    return u["lang"] or "uk"


async def count_referrals(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)
        )
        (n,) = await cur.fetchone()
        return n


# ---------------------------------------------------------------------------
# Алерти-правила
# ---------------------------------------------------------------------------

async def add_alert(user_id: int, coin_id: str, symbol: str, kind: str,
                    op: str, value: float, ref_price: float = 0.0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO alerts(user_id,coin_id,symbol,kind,op,value,ref_price,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (user_id, coin_id, symbol, kind, op, value, ref_price, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def list_alerts(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM alerts WHERE user_id=? AND active=1 ORDER BY id", (user_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def count_alerts(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM alerts WHERE user_id=? AND active=1", (user_id,)
        )
        (n,) = await cur.fetchone()
        return n


async def delete_alert(user_id: int, alert_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def all_active_alerts() -> list:
    """Усі активні алерти всіх користувачів (для фонового циклу)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM alerts WHERE active=1")
        return [dict(r) for r in await cur.fetchall()]


async def deactivate_alert(alert_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE alerts SET active=0 WHERE id=?", (alert_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

async def add_watch(user_id: int, coin_id: str, symbol: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO watchlist(user_id,coin_id,symbol) VALUES(?,?,?)",
            (user_id, coin_id, symbol),
        )
        await db.commit()


async def remove_watch(user_id: int, coin_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM watchlist WHERE user_id=? AND coin_id=?", (user_id, coin_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def list_watch(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT coin_id, symbol FROM watchlist WHERE user_id=?", (user_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# Портфель
# ---------------------------------------------------------------------------

async def add_holding(user_id: int, coin_id: str, symbol: str,
                      amount: float, buy_price: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO holdings(user_id,coin_id,symbol,amount,buy_price,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (user_id, coin_id, symbol, amount, buy_price, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def list_holdings(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM holdings WHERE user_id=? ORDER BY id", (user_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def delete_holding(user_id: int, holding_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM holdings WHERE id=? AND user_id=?", (holding_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def clear_holdings(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM holdings WHERE user_id=?", (user_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Журнал сигналів (для трекінгу точності)
# ---------------------------------------------------------------------------

async def log_signal(coin_id: str, symbol: str, direction: str, entry: float,
                     stop_loss: float, take_profit: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signals(coin_id,symbol,direction,entry,stop_loss,take_profit,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (coin_id, symbol, direction, entry, stop_loss, take_profit, int(time.time())),
        )
        await db.commit()
