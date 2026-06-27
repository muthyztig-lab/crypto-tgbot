# Algo-Trading R&D Bot

> Дослідницька платформа алгоритмічної крипто-торгівлі з керуванням через Telegram.
> Повний цикл: **збір даних → бектест → оптимізація параметрів → live-запуск на
> Binance (paper/testnet) → reconcile live vs backtest із розкладанням execution gap.**

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="aiogram" src="https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white">
  <img alt="Binance" src="https://img.shields.io/badge/Binance-spot%20%2B%20testnet-F0B90B?logo=binance&logoColor=white">
  <img alt="No heavy deps" src="https://img.shields.io/badge/deps-stdlib%20only-2ea043">
</p>

Працює «з коробки»: ринкові дані Binance публічні й не вимагають ключів. Власний
мінімальний клієнт біржі на `requests` + `hmac` (без ccxt/pandas/numpy) — щоб було
видно, що саме відбувається на рівні API, коли треба пояснювати розрив із бектестом.

---

## Навіщо це

Типова проблема алго-торгівлі: стратегія гарна **на бектесті**, але в реальному
виконанні «не летить». Цей бот побудований саме навколо питання **чому** —
і відповідає на нього числами, а не відчуттями.

Кожен бектест показує **два** результати:
- **Ідеальний** — вхід по ціні закриття бару-сигналу, без комісій і проковзування
  (верхня межа, яку часто видають за реальність);
- **Реалістичний** — вхід на відкритті *наступного* бару + комісії + slippage.

А `reconcile` після live-прогону розкладає розрив `ідеал → live` на складові:
запізнення виконання, комісії+проковзування і **residual** (усе незмодельоване:
пропущені бари, гранулярність полінгу, часткові виконання, поведінка біржі).

---

## Швидкий старт

```bash
pip install -r requirements.txt
python bot.py
```

1. Створіть бота у [@BotFather](https://t.me/BotFather) → `/newbot` → токен у `.env`:
   ```dotenv
   BOT_TOKEN=...
   ```
2. `python bot.py`, далі в Telegram: `/start`.

Режим за замовчуванням — **paper** (симуляція виконання на реальних даних, нуль
ризику). База `data/bot.db` створюється автоматично.

---

## Команди

| Команда | Що робить |
|---|---|
| `/strategies` | список стратегій і параметрів |
| `/backtest SYM STRAT [TF]` | бектест: ідеал vs реалізм + Buy&Hold |
| `/optimize SYM STRAT [TF]` | grid search параметрів + **walk-forward** (тест на перепідгонку) |
| `/run SYM STRAT [TF]` | запустити стратегію live (paper або Binance) |
| `/status`, `/runs` | активні прогони / історія |
| `/stop ID` | зупинити прогін |
| `/report ID` | **reconcile**: live vs backtest + розклад execution gap |
| `/mode` | поточний режим виконання і модель витрат |

`SYM`: `BTC`, `ETH`, `eth/usdt`… · `STRAT`: `ema_cross` (алиас `ema`),
`rsi_rev` (алиас `rsi`) · `TF`: `1m 5m 15m 1h 4h 1d`.

Приклад: `/backtest BTC ema 1h` → `/optimize BTC ema 1h` → `/run BTC ema 1h`
→ (через кілька барів) `/report 1`.

---

## Стратегії

Дві «перспективні на бектесті» стратегії — точка старту (як у ТЗ):

- **EMA Cross (trend)** — лонг, поки EMA(fast) > EMA(slow); вихід навпаки.
- **RSI Reversion (mean-revert)** — купити перепроданість (RSI < low), вийти на RSI > high.

Сигнал на барі `i` рахується **лише** з даних `[0..i]` — жодного зазирання в
майбутнє (типове джерело брехливого бектесту). Логіка *сигналу* і логіка
*виконання* навмисно розділені — execution gap живе саме у виконанні.

Додати свою стратегію: підкласити `Strategy` у [engine/strategies.py](engine/strategies.py)
(`target_positions` повертає цільову позицію 0/1 по барах) і додати в `STRATEGIES`.

---

## Налаштування виконання (`.env`)

| Змінна | Призначення | Типове |
|---|---|---|
| `TRADE_MODE` | `paper` (симуляція) або `live` (реальні ордери) | `paper` |
| `BINANCE_API_KEY/SECRET` | ключі для `live` (testnet або бій) | — |
| `BINANCE_TESTNET` | `1` = testnet.binance.vision, `0` = бій | `1` |
| `FEE_BPS` | комісія, базисні пункти (10 = 0.1%) | `10` |
| `SLIPPAGE_BPS` | модель проковзування | `5` |
| `EXEC_LATENCY_BARS` | запізнення виконання у барах (1 = реалізм) | `1` |
| `START_EQUITY` | стартовий капітал прогону, USDT | `1000` |
| `POLL_SECONDS` | період опитування біржі | `20` |
| `ADMIN_IDS` | хто може запускати торгівлю (порожнє = всі) | — |

> Щоб перейти на реальні гроші: `TRADE_MODE=live`, `BINANCE_TESTNET=0` і ключі з
> правами на спот-торгівлю. Починайте з малого депозиту.

---

## Архітектура

```
bot.py              точка входу → app.main
app/main.py         Telegram-пульт: команди, кнопки, форматування звітів
core/               settings (.env), db (async SQLite: runs/fills/equity), i18n, cache
exchange/binance.py мінімальний клієнт: публічні свічки + підписані ордери (HMAC)
engine/
  strategies.py     стратегії як чисті функції сигналів (EMA cross, RSI reversion)
  backtester.py     подієвий бектест: латентність + комісії + slippage
  metrics.py        Sharpe, CAGR, max DD, win rate, profit factor, expectancy
  optimizer.py      grid search + walk-forward (in-sample / out-of-sample)
  broker.py         виконання: PaperBroker (симуляція) / LiveBroker (Binance)
  runner.py         live-цикл на прогін: нові бари → сигнал → ордер → запис у БД
  reconcile.py      live vs backtest + декомпозиція execution gap
data/               bot.db (runtime, git-ignored)
```

Усі мережеві виклики йдуть через `asyncio.to_thread`, тож бот не блокується.
Прогони переживають рестарт: стан (cash/units) відновлюється з таблиці `fills`,
а `runner.resume_all()` піднімає всі прогони зі статусом `running`.

---

> ⚠️ Бектести, сигнали та live-результати — **не фінансова порада**. Алго-торгівля
> реальними коштами пов'язана з ризиком втрати капіталу.
