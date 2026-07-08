import os
import json
import time

import aiosqlite

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    symbol       TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    strategy     TEXT    NOT NULL,
    params_json  TEXT    DEFAULT '{}',
    mode         TEXT    DEFAULT 'paper',
    fee_bps      REAL    DEFAULT 10,
    slippage_bps REAL    DEFAULT 5,
    start_equity REAL    DEFAULT 1000,
    start_ts     INTEGER DEFAULT 0,
    stop_ts      INTEGER DEFAULT 0,
    status       TEXT    DEFAULT 'running',
    last_pos     REAL    DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    ts           INTEGER NOT NULL,
    bar_ts       INTEGER DEFAULT 0,
    side         TEXT    NOT NULL,
    qty          REAL    NOT NULL,
    ref_price    REAL    NOT NULL,
    exec_price   REAL    NOT NULL,
    fee          REAL    DEFAULT 0,
    slippage_bps REAL    DEFAULT 0
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
    os.makedirs(DATA_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def create_run(user_id, symbol, timeframe, strategy, params, mode,
                     fee_bps, slippage_bps, start_equity) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO runs(user_id,symbol,timeframe,strategy,params_json,mode,"
            "fee_bps,slippage_bps,start_equity,start_ts,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'running')",
            (user_id, symbol, timeframe, strategy, json.dumps(params), mode,
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
    query = "SELECT * FROM runs WHERE user_id=?"
    args = [user_id]
    if status:
        query += " AND status=?"
        args.append(status)
    query += " ORDER BY id DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, args)
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
