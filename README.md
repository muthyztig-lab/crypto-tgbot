# Crypto Risk Bot

> A Telegram bot for crypto market analysis and **risk scoring** — charts, signals,
> on-chain token safety checks, derivatives, news + AI, portfolio tracking, smart
> alerts, and Telegram Stars monetization.

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="aiogram" src="https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white">
  <img alt="No API keys" src="https://img.shields.io/badge/API%20keys-not%20required-2ea043">
</p>

**Everything works out of the box — no API keys required.** Market data comes from
public CoinGecko and OKX endpoints. Optional keys only switch on extra features.

---

## ✨ Features

**Market analysis**
- Pick a coin with buttons or by typing a ticker/name (e.g. `pepe`)
- Chart timeframes from **1 minute to 1 year** (1m, 5m, 15m, 1H, 4H, 1D, 1W, 1M, 3M, 6M, 1Y)
- **Line and candlestick charts** on any timeframe, with support/resistance levels
- **Risk score 0–100** plus RSI, volatility, trend, max drawdown
- **Fear & Greed Index**
- **LONG / SHORT signals** with ATR-based Stop Loss / Take Profit and Risk/Reward
- **Whole-market overview** (`/market`): market cap, BTC/ETH dominance, volume
- **Top gainers / losers** over 24h (`/top`)

**Pro toolkit (v4)**
- **On-chain token risk** (`/risk <network> <address>`) — honeypot, buy/sell tax,
  owner privileges, liquidity lock, holder concentration (GoPlus + honeypot.is)
- **Smart alerts** (`/alert BTC price > 70000`) — rules on `price`, `pct`, `rsi`, `volume`
- **Derivatives** (`/deriv BTC`) — funding rate, open interest, long/short ratio (OKX)
- **Technical signals** (`/signals BTC`) — MACD + Bollinger + RSI + EMA cross + divergences
- **Backtesting** (`/backtest BTC`) — EMA-cross & RSI strategies vs Buy & Hold
- **News + AI** (`/news`, `/ask`) — RSS/CryptoPanic headlines with sentiment, OpenAI helper
- **Portfolio** (`/portfolio`, `/addcoin BTC 0.5 60000`) — positions, P&L, allocation
- **Monetization** — PRO subscription via **Telegram Stars**, with referrals

**Polish**
- Auto-cleanup of stale messages — the chat always shows only the current card
- Update timestamps down to the second
- No emoji — all visuals are generated as SVG cards and rendered to PNG
  (via `cairosvg`, or a built-in Pillow rasterizer that needs no system libraries)
- Localization `uk` / `en` (`/lang en`), per-user rate limiting, optional Sentry

> Intraday timeframes (1m–4H) pull native OKX candles (60–96 real bars). If a coin
> isn't on OKX, the bot suggests using a 1D+ timeframe (CoinGecko data).

---

## 🚀 Quick start

```bash
pip install -r requirements.txt
python bot.py
```

1. Create a bot with [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Put it in `.env`:
   ```dotenv
   BOT_TOKEN=your_token_here
   ```
3. Run `python bot.py` and send `/start` to your bot in Telegram

On first launch the SQLite database `data/bot.db` is created automatically.
Recommended Python: **3.12** (tested).

---

## 🔑 Optional keys (`.env`)

Only `BOT_TOKEN` is required. Everything else just unlocks extra features.

| Variable | Enables | Without it |
|---|---|---|
| `OPENAI_API_KEY` | `/ask` AI helper + AI analysis explanations | feature politely disabled |
| `OPENAI_MODEL` | model for the AI helper | `gpt-4o-mini` |
| `CRYPTOPANIC_API_KEY` | votes/sentiment in news | RSS feeds still work |
| `SENTRY_DSN` | error monitoring | disabled (local logs only) |
| `REDIS_URL` | shared cache across instances | in-memory cache |
| `PRO_PRICE_STARS` / `PRO_DAYS` | PRO price & duration | 299 ⭐ / 30 days |
| `RATE_*`, `ALERTS_*` | rate & alert-count limits | sensible defaults |
| `DEFAULT_LANG` | default language (`uk`/`en`) | `uk` |

`.env` is git-ignored, so your token stays out of version control.

---

## 💬 Commands

| Command | Description |
|---------|-------------|
| `/start` | coin selection menu |
| `/market` | whole-market overview + Fear & Greed |
| `/top` | top gainers & losers (24h) |
| `/favorites` | favorites & price-change alerts |
| `/risk <net> <addr>` | on-chain token risk check |
| `/alert`, `/alerts`, `/delalert` | smart alert rules |
| `/deriv`, `/signals`, `/backtest` | derivatives, confluence signals, backtest |
| `/news`, `/ask` | news + sentiment, AI helper (PRO) |
| `/portfolio`, `/addcoin`, `/delcoin` | portfolio tracking |
| `/upgrade`, `/pro` | PRO subscription (Telegram Stars) |
| `/lang` | switch language (`uk`/`en`) |
| `/help` | help |

You can also just send a ticker or name as plain text.

---

## 📈 What the risk score means

| Score | Category |
|-------|----------|
| 0–29 | LOW |
| 30–54 | MODERATE |
| 55–74 | HIGH |
| 75–100 | VERY HIGH |

Components: annualized volatility (up to 40), 30-day max drawdown (up to 30),
RSI extremes (up to 15), market-cap size (up to 15).

**LONG / SHORT signal** weighs EMA12/EMA48 trend (±2.0), RSI (±1.5), momentum
(±1.0) and 24h change (±0.5), then picks a direction with a confidence %.
Levels: Stop Loss = price ∓ 1.5×ATR, Take Profit = price ± 2.5×ATR (R/R ≈ 1:1.67).

---

## 🐳 Docker

```bash
docker compose up -d --build
docker compose logs -f bot
```

The database and favorites live in the `./data` volume and survive restarts.
The `redis` service is optional — remove it if you don't use the shared cache.

Database backup: `python scripts/backup.py` (writes to `data/backups/`).

---

## 🗂️ Project structure

```
bot.py            entry point (thin shim → app.main)
app/              main (handlers, keyboards, message lifecycle),
                  alerts (rules + background loop), payments (Telegram Stars),
                  ratelimit (per-user middleware)
core/             settings (.env), db (async SQLite), cache (Redis/memory),
                  storage (favorites.json), i18n (uk/en)
sources/          market_data (CoinGecko/OKX), onchain (GoPlus + honeypot.is),
                  derivatives (OKX), news (RSS/CryptoPanic)
analytics/        analysis (risk score, RSI, ATR, S/R), indicators (MACD,
                  Bollinger, divergences), signals (LONG/SHORT), backtest,
                  portfolio, ai (OpenAI)
render/           svg_render (SVG cards), pil_raster (SVG→PNG on Pillow), cards
data/             runtime data (bot.db, favorites.json, backups/) — git-ignored
scripts/          backup.py
```

All network calls run in threads (`asyncio.to_thread`), so the bot never blocks.

---

> ⚠️ Signals, backtests and risk scores are **not financial advice**.
