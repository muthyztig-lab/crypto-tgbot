# Algo-Trading R&D Bot

> A research platform for algorithmic crypto trading, controlled from Telegram.
> Full loop: **data → backtest → parameter optimization → live run on Binance
> (paper/testnet) → reconcile of live vs backtest with an execution-gap breakdown.**

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="aiogram" src="https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white">
  <img alt="Binance" src="https://img.shields.io/badge/Binance-spot%20%2B%20testnet-F0B90B?logo=binance&logoColor=white">
  <img alt="No heavy deps" src="https://img.shields.io/badge/deps-stdlib%20only-2ea043">
</p>

Runs out of the box: Binance market data is public and needs no keys. The exchange
client is a minimal `requests` + `hmac` implementation (no ccxt / pandas / numpy),
so it stays obvious what happens at the API level when you have to explain why the
live result differs from the backtest.

---

## Why this exists

The classic problem in algo trading: a strategy looks great **in the backtest**
but underperforms in real execution. This bot is built around answering **why** —
with numbers, not gut feeling.

Every backtest reports **two** results:
- **Ideal** — fill at the signal bar's close, zero fees, zero slippage (the upper
  bound that is often mistaken for reality);
- **Realistic** — fill at the *next* bar's open + fees + slippage.

After a live run, `reconcile` decomposes the `ideal → live` gap into:
execution latency, fees + slippage, and **residual** (everything unmodeled: missed
bars, polling granularity, partial fills, real exchange behavior).

---

## Quick start

```bash
pip install -r requirements.txt
python bot.py
```

1. Create a bot via [@BotFather](https://t.me/BotFather) → `/newbot` → put the token in `.env`:
   ```dotenv
   BOT_TOKEN=...
   ```
2. Run `python bot.py`, then send `/start` in Telegram.

The default mode is **paper** (execution simulated on real market data, zero risk).
The SQLite database `data/bot.db` is created automatically on first run.

---

## Commands

| Command | Description |
|---|---|
| `/strategies` | list strategies and their parameters |
| `/backtest SYM STRAT [TF]` | backtest: ideal vs realistic + Buy & Hold |
| `/optimize SYM STRAT [TF]` | grid search + **walk-forward** (overfit check) |
| `/run SYM STRAT [TF]` | start a strategy live (paper or Binance) |
| `/status`, `/runs` | active runs / run history |
| `/stop ID` | stop a run |
| `/report ID` | **reconcile**: live vs backtest + execution-gap breakdown |
| `/mode` | current execution mode and cost model |

`SYM`: `BTC`, `ETH`, `eth/usdt`, … · `STRAT`: `ema_cross` (alias `ema`),
`rsi_rev` (alias `rsi`) · `TF`: `1m 5m 15m 1h 4h 1d`.

Example: `/backtest BTC ema 1h` → `/optimize BTC ema 1h` → `/run BTC ema 1h`
→ (after a few bars) `/report 1`.

---

## Strategies

Two "backtest-promising" strategies as a starting point:

- **EMA Cross (trend)** — long while EMA(fast) > EMA(slow), flat otherwise.
- **RSI Reversion (mean-revert)** — buy oversold (RSI < low), exit on RSI > high.

The signal at bar `i` is computed from data `[0..i]` only — no lookahead bias (a
common source of a lying backtest). Signal logic and execution logic are kept
separate on purpose — the execution gap lives entirely in execution.

Add your own strategy: subclass `Strategy` in [engine/strategies.py](engine/strategies.py)
(`target_positions` returns a 0/1 target position per bar) and register it in
`STRATEGIES`.

---

## Execution settings (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `TRADE_MODE` | `paper` (simulation) or `live` (real orders) | `paper` |
| `BINANCE_API_KEY/SECRET` | keys for `live` (testnet or mainnet) | — |
| `BINANCE_TESTNET` | `1` = testnet.binance.vision, `0` = mainnet | `1` |
| `FEE_BPS` | fee, basis points (10 = 0.1%) | `10` |
| `SLIPPAGE_BPS` | slippage model | `5` |
| `EXEC_LATENCY_BARS` | execution latency in bars (1 = realistic) | `1` |
| `START_EQUITY` | run starting capital, USDT | `1000` |
| `POLL_SECONDS` | exchange poll interval | `20` |
| `ADMIN_IDS` | who may start trading (empty = everyone) | — |

> To go live: set `TRADE_MODE=live` and add keys. Testnet keys are free at
> testnet.binance.vision (permissions: TRADE + USER_DATA). For real liquidity and
> slippage set `BINANCE_TESTNET=0` with mainnet keys and start with a small deposit.

---

## Architecture

```
bot.py              entry point → app.main
app/main.py         Telegram control panel: commands, buttons, report formatting
app/ratelimit.py    per-user rate limiting middleware
core/settings.py    .env loader and configuration
core/db.py          async SQLite: runs / fills / equity_points
exchange/binance.py minimal client: public klines + signed orders (HMAC)
engine/
  strategies.py     strategies as pure signal functions (EMA cross, RSI reversion)
  backtester.py     event-driven backtest: latency + fees + slippage
  metrics.py        Sharpe, CAGR, max DD, win rate, profit factor, expectancy
  optimizer.py      grid search + walk-forward (in-sample / out-of-sample)
  broker.py         execution: PaperBroker (simulation) / LiveBroker (Binance)
  runner.py         per-run live loop: new bar → signal → order → persist to DB
  reconcile.py      live vs backtest + execution-gap decomposition
data/               bot.db (runtime, git-ignored)
```

All network calls run via `asyncio.to_thread`, so the bot never blocks. Runs
survive restarts: state (cash/units) is rebuilt from the `fills` table, and
`runner.resume_all()` re-launches every run still marked `running`.

---

> ⚠️ Backtests, signals and live results are **not financial advice**. Trading real
> funds with an algorithm carries the risk of losing capital.
