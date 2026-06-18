# Crypto Risk Bot v4 — налаштування та нові можливості

Версія 4 перетворює бота з «аналітичного» на повноцінний **платний продукт**:
on-chain перевірка токенів, деривативи, тех.сигнали, бектести, новини+AI,
портфель, гнучкі алерти, монетизація через Telegram Stars та інфраструктура
для продакшену. **Усе працює одразу — без жодного ключа.** Ключі лише вмикають
додаткові фічі.

---

## 1. Швидкий старт (як і раніше)

```bash
pip install -r requirements.txt
python bot.py
```

Токен уже зашитий у `config.py` — нічого міняти не треба. При першому запуску
автоматично створюється база `data/bot.db`.

> Рекомендований Python — **3.12** (на ньому все протестовано).

---

## 2. Опційні ключі (.env)

Скопіюйте приклад і заповніть лише те, що потрібно:

```bash
cp .env.example .env
```

| Змінна | Що вмикає | Без неї |
|---|---|---|
| `OPENAI_API_KEY` | AI-помічник `/ask` та AI-пояснення аналізу | фіча показує ввічливе «вимкнено» |
| `CRYPTOPANIC_API_KEY` | голоси/сентимент у новинах | працює RSS (Cointelegraph, Coindesk) |
| `SENTRY_DSN` | моніторинг помилок | вимкнено |
| `REDIS_URL` | спільний кеш між інстансами | кеш у пам'яті |
| `PRO_PRICE_STARS` / `PRO_DAYS` | ціна та тривалість PRO | 299 ⭐ / 30 днів |
| `RATE_*`, `ALERTS_*` | ліміти частоти та кількості алертів | розумні дефолти |
| `DEFAULT_LANG` | мова за замовчуванням (uk/en) | uk |

Жоден ключ не є обовʼязковим. Токен бота в `.env` **не зберігається** — він у `config.py`.

---

## 3. Нові можливості (7 блоків)

**1. On-chain ризик токена** — `/risk <мережа> <адреса>`
Перевірка honeypot, податків купівлі/продажу, прав власника (mint, pausable,
proxy, selfdestruct), блокування ліквідності, концентрації холдерів.
Джерела: GoPlus Security + honeypot.is. Підсумковий rug-pull бал 0–100.
Напр.: `/risk eth 0xdAC17F958D2ee523a2206206994597C13D831ec7`

**2. Розумні алерти** — `/alert BTC price > 70000`
Типи правил: `price`, `pct` (зміна %), `rsi`, `volume`. Фоновий цикл перевіряє
щотижні 30 с. `/alerts` — список, `/delalert <id>` — видалити. Старі % -алерти
по «обраному» теж працюють. Free — до 3 правил, PRO — до 100.

**3. Монетизація** — `/upgrade`, `/pro`
Підписка PRO через **Telegram Stars** (без банку/Stripe). Реферальна система:
діліться `https://t.me/<bot>?start=<ваш_id>`. Дані користувачів, тарифи,
алерти, портфель — у SQLite (`data/bot.db`).

**4. Деривативи, тех.сигнали, бектест**
- `/deriv BTC` — funding rate, open interest, long/short ratio (OKX)
- `/signals BTC` — конфлюенс MACD + Bollinger + RSI + EMA-крос + дивергенції
- `/backtest BTC` — історична перевірка стратегій EMA-крос і RSI vs Buy&Hold

**5. AI + новини**
- `/news [тикер]` — заголовки + автосентимент (RSS, опційно CryptoPanic)
- `/ask <питання>` *(PRO)* — AI-помічник
- кнопка «AI-пояснення» *(PRO)* під карткою аналізу

**6. Портфель** — `/portfolio`, `/addcoin BTC 0.5 60000`, `/delcoin <id>`
Ручний облік позицій, поточна вартість, P&L по кожній і загалом, розподіл %.
Watchlist: `/watch BTC`, `/watchlist`. Free — до 3 позицій.

**7. Інфраструктура**
- Локалізація `uk`/`en`: `/lang en`
- Rate-limiting по користувачу (free/pro)
- Sentry-моніторинг (опційно)
- Docker: `docker compose up -d --build` (том `data/`, опційний Redis)
- Бекап БД: `python scripts/backup.py` (зберігає у `data/backups/`)

---

## 4. Docker (продакшен)

```bash
cp .env.example .env      # за бажанням
docker compose up -d --build
docker compose logs -f bot
```

База та обране зберігаються в томі `./data` і переживають перезапуск.
Сервіс `redis` опційний — приберіть його, якщо не використовуєте кеш.

---

## 5. Архітектура (нові файли)

```
settings.py     — читання .env (токен не чіпає)
db.py           — async SQLite: users / alerts / watchlist / holdings
cache.py        — Redis або памʼять
onchain.py      — GoPlus + honeypot.is        (блок 1)
alerts.py       — алерти-правила + цикл        (блок 2)
payments.py     — Telegram Stars               (блок 3)
derivatives.py  — funding/OI/long-short (OKX)  (блок 4)
indicators.py   — MACD/Bollinger/дивергенції   (блок 4)
backtest.py     — бектести стратегій           (блок 4)
news.py, ai.py  — новини + OpenAI              (блок 5)
portfolio.py    — облік позицій                (блок 6)
i18n.py         — uk/en                         (блок 7)
ratelimit.py    — middleware лімітів           (блок 7)
cards.py        — нові SVG-картки
```

Усі мережеві виклики — у потоках (`asyncio.to_thread`), бот не блокується.
Графіка — як і раніше, SVG → PNG (cairosvg або вбудований растеризатор на
Pillow, тож працює навіть без системних бібліотек на Windows).

> Сигнали, бектести та оцінки **не є фінансовою порадою**.
