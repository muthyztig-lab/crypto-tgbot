import os
import time
import aiosqlite

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
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
-- ───────────── Алго-торгівля (R&D): прогони, виконання, equity ─────────────
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    symbol       TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    strategy     TEXT    NOT NULL,
    params_json  TEXT    DEFAULT '{}',
    mode         TEXT    DEFAULT 'paper',     -- paper | live
    fee_bps      REAL    DEFAULT 10,
    slippage_bps REAL    DEFAULT 5,
    start_equity REAL    DEFAULT 1000,
    start_ts     INTEGER DEFAULT 0,
    stop_ts      INTEGER DEFAULT 0,
    status       TEXT    DEFAULT 'running',    -- running | stopped
    last_pos     REAL    DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fills (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    bar_ts     INTEGER DEFAULT 0,             -- час бару-сигналу
    side       TEXT    NOT NULL,              -- BUY | SELL
    qty        REAL    NOT NULL,
    ref_price  REAL    NOT NULL,             -- ціна сигналу (закриття бару)
    exec_price REAL    NOT NULL,             -- фактична ціна виконання
    fee        REAL    DEFAULT 0,
    slippage_bps REAL  DEFAULT 0
);
CREATE TABLE IF NOT EXISTS equity_points (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    equity   REAL    NOT NULL,
    position REAL    DEFAULT 0,
    price    REAL    DEFAULT 0
);
"""


async def init() -> None:
    """Створює файл БД та таблиці, якщо їх немає."""
    os.makedirs(DATA_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


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


async def log_signal(coin_id: str, symbol: str, direction: str, entry: float,
                     stop_loss: float, take_profit: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signals(coin_id,symbol,direction,entry,stop_loss,take_profit,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (coin_id, symbol, direction, entry, stop_loss, take_profit, int(time.time())),
        )
        await db.commit()


# ───────────────────────── Алго-торгівля: прогони ─────────────────────────

import json as _json


async def create_run(user_id, symbol, timeframe, strategy, params, mode,
                     fee_bps, slippage_bps, start_equity) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO runs(user_id,symbol,timeframe,strategy,params_json,mode,"
            "fee_bps,slippage_bps,start_equity,start_ts,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'running')",
            (user_id, symbol, timeframe, strategy, _json.dumps(params), mode,
             fee_bps, slippage_bps, start_equity, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def get_run(run_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM runs WHERE id=?", (run_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_runs(user_id: int, status: str | None = None) -> list:
    q = "SELECT * FROM runs WHERE user_id=?"
    args = [user_id]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY id DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(q, args)
        return [dict(r) for r in await cur.fetchall()]


async def all_running_runs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM runs WHERE status='running'")
        return [dict(r) for r in await cur.fetchall()]


async def stop_run(run_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE runs SET status='stopped', stop_ts=? WHERE id=?",
            (int(time.time()), run_id))
        await db.commit()


async def set_run_pos(run_id: int, pos: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE runs SET last_pos=? WHERE id=?", (pos, run_id))
        await db.commit()


async def add_fill(run_id, ts, bar_ts, side, qty, ref_price, exec_price,
                   fee, slippage_bps) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO fills(run_id,ts,bar_ts,side,qty,ref_price,exec_price,fee,slippage_bps)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, ts, bar_ts, side, qty, ref_price, exec_price, fee, slippage_bps))
        await db.commit()


async def list_fills(run_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM fills WHERE run_id=? ORDER BY ts", (run_id,))
        return [dict(r) for r in await cur.fetchall()]


async def add_equity_point(run_id, ts, equity, position, price) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO equity_points(run_id,ts,equity,position,price) VALUES(?,?,?,?,?)",
            (run_id, ts, equity, position, price))
        await db.commit()


async def list_equity(run_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT ts,equity,position,price FROM equity_points WHERE run_id=? ORDER BY ts",
            (run_id,))
        return [dict(r) for r in await cur.fetchall()]
