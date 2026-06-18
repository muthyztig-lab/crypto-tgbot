"""
Генерація SVG-карток (замість емодзі — векторна графіка) та
конвертація SVG -> PNG для відправки в Telegram.

Картки:
- build_analysis_svg — повний аналіз монети (лінійний або свічковий графік,
  рівні підтримки/опору, шкала ризику, метрики, Fear & Greed)
- build_signal_svg   — сигнал LONG/SHORT з рівнями Stop Loss / Take Profit
- build_market_svg   — глобальний огляд крипторинку
- build_movers_svg   — топ зростання / падіння за 24 години
- build_alert_svg    — цінове сповіщення для обраної монети

SVG -> PNG:
1) cairosvg, якщо в системі є бібліотека cairo (Linux/macOS)
2) інакше — власний растеризатор на Pillow (pil_raster.py),
   який працює на Windows без жодних системних бібліотек.
"""

import html
import math

W = 900
BG = "#0f1419"
PANEL = "#1a2129"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
GREEN = "#2ea043"
RED = "#da3633"
BLUE = "#388bfd"
YELLOW = "#d29922"
ORANGE = "#e8590c"


# ===========================================================================
# Допоміжні функції форматування
# ===========================================================================

def _fmt_price(p):
    """Гарне форматування ціни в USD залежно від масштабу."""
    if p is None:
        return "-"
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:.6f}"


def _fmt_big(v):
    """Скорочений запис великих чисел: $1.27T, $30.0B, $5.2M."""
    if v is None:
        return "-"
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _risk_color(score):
    """Колір ризик-балу: зелений -> жовтий -> помаранчевий -> червоний."""
    if score < 30:
        return GREEN
    if score < 55:
        return YELLOW
    if score < 75:
        return ORANGE
    return RED


def _fng_color(value):
    """Колір Fear & Greed: страх = червоний, жадібність = зелений."""
    if value < 25:
        return RED
    if value < 45:
        return ORANGE
    if value < 55:
        return YELLOW
    return GREEN


def _text(x, y, s, size=16, fill=TEXT, bold=False, anchor=None):
    """Скорочення для SVG-тексту."""
    extra = ' font-weight="bold"' if bold else ""
    if anchor:
        extra += f' text-anchor="{anchor}"'
    # Екрануємо текст (назви/тикери монет приходять із зовнішнього API і можуть
    # містити & < > " — без екранування це ламає XML-парсинг або дає інʼєкцію)
    safe = html.escape(str(s), quote=True)
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"{extra} '
        f'font-family="Arial">{safe}</text>'
    )


def _tile(x, y, w, h, label, value, value_color=TEXT, label_size=12, value_size=17):
    """Прямокутна плитка-метрика: підпис зверху, значення знизу."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}"/>'
        + _text(x + w / 2, y + 26, label, label_size, MUTED, anchor="middle")
        + _text(x + w / 2, y + 56, value, value_size, value_color, bold=True,
                anchor="middle")
    )


def _arrow(direction, x, y, size=22):
    """Векторна стрілка вгору/вниз замість емодзі."""
    if direction == "up":
        return (
            f'<polygon points="{x},{y + size} {x + size / 2},{y} '
            f'{x + size},{y + size}" fill="{GREEN}"/>'
        )
    return (
        f'<polygon points="{x},{y} {x + size / 2},{y + size} '
        f'{x + size},{y}" fill="{RED}"/>'
    )


def _gauge(value, cx, cy, r, color, max_value=100):
    """Дугова шкала 0..max_value із числом у центрі."""
    ang = math.radians(180 - (value / max_value) * 180)
    x1, y1 = cx - r, cy
    x2, y2 = cx + r, cy
    nx, ny = cx + r * math.cos(ang), cy - r * math.sin(ang)
    return (
        f'<path d="M {x1} {y1} A {r} {r} 0 0 1 {x2} {y2}" fill="none" '
        f'stroke="#2d333b" stroke-width="14" stroke-linecap="butt"/>'
        f'<path d="M {x1} {y1} A {r} {r} 0 0 1 {nx:.1f} {ny:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="14" stroke-linecap="butt"/>'
        + _text(cx, cy - 12, f"{value:.0f}", 34, color, bold=True, anchor="middle")
    )


# ===========================================================================
# Графіки: лінія та свічки
# ===========================================================================

def _price_scale(values, y, h):
    """Повертає функцію перетворення ціни у координату Y."""
    vmin, vmax = min(values), max(values)
    rng = (vmax - vmin) or 1.0

    def to_y(p):
        return y + h - ((p - vmin) / rng) * h

    return to_y, vmin, vmax


def _line_chart(prices, x, y, w, h, color):
    """Лінійний графік ціни із заливкою під лінією."""
    if len(prices) < 2:
        return ""
    to_y, _, _ = _price_scale(prices, y, h)
    n = len(prices)
    pts = [f"{x + (i / (n - 1)) * w:.1f},{to_y(p):.1f}" for i, p in enumerate(prices)]
    poly = " ".join(pts)
    area = f"{x:.1f},{y + h:.1f} {poly} {x + w:.1f},{y + h:.1f}"
    return (
        f'<polygon points="{area}" fill="{color}" opacity="0.12"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.5"/>'
    )


def _candle_chart(ohlc, x, y, w, h):
    """Свічковий графік: тіні (полілінії) + тіла (прямокутники)."""
    if len(ohlc) < 2:
        return ""
    highs = [c[2] for c in ohlc]
    lows = [c[3] for c in ohlc]
    to_y, _, _ = _price_scale(highs + lows, y, h)

    n = len(ohlc)
    step = w / n
    body_w = max(2.0, step * 0.62)
    parts = []
    for i, (_, o, hi, lo, cl) in enumerate(ohlc):
        cx = x + step * (i + 0.5)
        color = GREEN if cl >= o else RED
        # Тінь (wick)
        parts.append(
            f'<polyline points="{cx:.1f},{to_y(hi):.1f} {cx:.1f},{to_y(lo):.1f}" '
            f'fill="none" stroke="{color}" stroke-width="1.4"/>'
        )
        # Тіло свічки
        top, bot = to_y(max(o, cl)), to_y(min(o, cl))
        if bot - top < 1.6:
            bot = top + 1.6
        parts.append(
            f'<rect x="{cx - body_w / 2:.1f}" y="{top:.1f}" '
            f'width="{body_w:.1f}" height="{bot - top:.1f}" fill="{color}"/>'
        )
    return "".join(parts)


def _level_line(price, values, x, y, w, h, color, label):
    """Горизонтальна лінія рівня (підтримка/опір) із підписом."""
    to_y, vmin, vmax = _price_scale(values, y, h)
    if not (vmin <= price <= vmax):
        return ""
    ly = to_y(price)
    return (
        f'<polyline points="{x},{ly:.1f} {x + w},{ly:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="1"/>'
        + _text(x + w, ly - 5, f"{label} {_fmt_price(price)}", 12, color,
                anchor="end")
    )


# ===========================================================================
# Картка 1: повний аналіз монети
# ===========================================================================

def build_analysis_svg(a: dict, chart_mode: str = "line", ohlc: list = None,
                       fng: dict = None) -> str:
    """
    Картка аналізу 900x560.

    a          — результат full_analysis()
    chart_mode — "line" або "candle"
    ohlc       — свічки для режиму candle
    fng        — Fear & Greed {"value":, "label":}
    """
    H = 560
    info = a["info"]
    prices = a["prices"]
    chg = info["change_24h_pct"]
    chg_color = GREEN if chg >= 0 else RED
    risk_col = _risk_color(a["risk_score"])
    trend_txt = {1: "Висхідний", -1: "Низхідний", 0: "Боковий"}[a["trend"]]
    trend_col = {1: GREEN, -1: RED, 0: MUTED}[a["trend"]]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        # --- Заголовок ---
        _text(40, 58, f'{info["name"]} ({info["symbol"]})', 34, TEXT, bold=True),
        _text(40, 92, _fmt_price(info["price"]), 40, TEXT, bold=True),
        _arrow("up" if chg >= 0 else "down", 40, 108),
        _text(72, 128, f"{chg:+.2f}% за 24 год", 24, chg_color),
        # --- Панель графіка ---
        f'<rect x="30" y="150" width="560" height="240" rx="12" fill="{PANEL}"/>',
        _text(50, 180, f'Ціна, {a["tf_label"]} (USD)', 16, MUTED),
    ]

    # Графік: свічки або лінія + рівні підтримки/опору
    cx, cy, cw, ch = 50, 195, 520, 170
    if chart_mode == "candle" and ohlc:
        parts.append(_candle_chart(ohlc, cx, cy, cw, ch))
        level_values = [c[2] for c in ohlc] + [c[3] for c in ohlc]
        mode_txt = "свічки"
    else:
        parts.append(_line_chart(prices, cx, cy, cw, ch, BLUE))
        level_values = prices
        mode_txt = "лінія"
    parts.append(_level_line(a["resistance"], level_values, cx, cy, cw, ch,
                             ORANGE, "Опір"))
    parts.append(_level_line(a["support"], level_values, cx, cy, cw, ch,
                             "#3fb950", "Підтримка"))
    parts.append(_text(570, 180, mode_txt, 13, MUTED, anchor="end"))

    # --- Панель ризику ---
    parts += [
        f'<rect x="610" y="150" width="260" height="240" rx="12" fill="{PANEL}"/>',
        _text(740, 180, "РИЗИК-БАЛ (0-100)", 16, MUTED, anchor="middle"),
        _gauge(a["risk_score"], 740, 310, 90, risk_col),
        _text(740, 350, a["risk_category"], 20, risk_col, bold=True,
              anchor="middle"),
    ]

    # --- Нижній ряд метрик (7 плиток) ---
    fng = fng or {"value": 50, "label": "-"}
    metrics = [
        ("Волатильність", f'{a["volatility_pct"]}%', TEXT),
        ("RSI (14)", f'{a["rsi"]}', TEXT),
        ("Просадка 30д", f'{a["max_drawdown_pct"]}%', TEXT),
        ("Тренд", trend_txt, trend_col),
        ("Капіталізація", _fmt_big(info["market_cap"]), TEXT),
        ("Обсяг 24г", _fmt_big(info["volume_24h"]), TEXT),
        ("Страх/Жадібн.", f'{fng["value"]}', _fng_color(fng["value"])),
    ]
    bx, by, gap = 30, 410, 10
    bw = (W - 2 * bx - (len(metrics) - 1) * gap) / len(metrics)
    for i, (label, value, col) in enumerate(metrics):
        parts.append(_tile(bx + i * (bw + gap), by, bw, 80, label, value, col,
                           label_size=11, value_size=16))

    parts += [
        _text(40, H - 18, f'Оновлено: {a["updated_at"]}', 15, MUTED),
        "</svg>",
    ]
    return "".join(parts)


# ===========================================================================
# Картка 2: сигнал LONG / SHORT із рівнями
# ===========================================================================

def build_signal_svg(a: dict, sig: dict) -> str:
    """Картка сигналу: напрямок, вхід/SL/TP, таблиця факторів."""
    H = 36 * len(sig["reasons"]) + 24 + 222 + 50  # таблиця + шапка + футер
    info = a["info"]
    d = sig["direction"]
    col = GREEN if d == "LONG" else (RED if d == "SHORT" else MUTED)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        _text(40, 56, f'{info["name"]} ({info["symbol"]}) — сигнал', 30, TEXT,
              bold=True),
        # --- Великий блок напрямку ---
        f'<rect x="30" y="84" width="260" height="120" rx="14" fill="{PANEL}" '
        f'stroke="{col}" stroke-width="3"/>',
        _text(160, 144, d, 42, col, bold=True, anchor="middle"),
        _text(160, 182, f'впевненість {sig["confidence"]}%', 18, MUTED,
              anchor="middle"),
    ]

    # --- Плитки: вхід, Stop Loss, Take Profit, Risk/Reward ---
    tiles = [
        ("Вхід (ціна зараз)", _fmt_price(sig["entry"]), TEXT),
        ("Stop Loss", _fmt_price(sig["stop_loss"]), RED),
        ("Take Profit", _fmt_price(sig["take_profit"]), GREEN),
        ("Risk / Reward", f'1 : {sig["risk_reward"]}', BLUE),
    ]
    tx, ty, tgap = 310, 84, 10
    tw = (W - tx - 30 - 3 * tgap) / 4
    for i, (label, value, vcol) in enumerate(tiles):
        parts.append(_tile(tx + i * (tw + tgap), ty, tw, 120, label, value, vcol,
                           label_size=12, value_size=17))
        # Зміщуємо значення нижче по центру плитки (стандартна плитка 80px)
    # Примітка: _tile малює значення на y+56 — для плиток 120px це виглядає добре

    # --- Таблиця факторів ---
    rows = sig["reasons"]
    table_h = 36 * len(rows) + 24
    parts.append(
        f'<rect x="30" y="222" width="840" height="{table_h}" rx="12" '
        f'fill="{PANEL}"/>'
    )
    y = 252
    for name, value, verdict in rows:
        vcol = GREEN if "лонг" in verdict else (RED if "шорт" in verdict else MUTED)
        parts += [
            _text(56, y, name, 17, TEXT),
            _text(380, y, value, 17, MUTED),
            _text(660, y, verdict, 17, vcol, bold=True),
        ]
        y += 36

    parts += [
        _text(40, H - 18,
              f'Оновлено: {a["updated_at"]} | SL/TP розраховано за ATR | '
              f'Не є фінансовою порадою', 15, MUTED),
        "</svg>",
    ]
    return "".join(parts)


# ===========================================================================
# Картка 3: глобальний огляд ринку
# ===========================================================================

def build_market_svg(g: dict, fng: dict, time_str: str) -> str:
    """Картка огляду крипторинку 900x420."""
    H = 420
    chg = g["mcap_change_24h_pct"]
    chg_color = GREEN if chg >= 0 else RED
    fng_col = _fng_color(fng["value"])

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        _text(40, 56, "Огляд крипторинку", 32, TEXT, bold=True),
        # --- Загальна капіталізація ---
        _text(40, 110, "Загальна капіталізація", 17, MUTED),
        _text(40, 156, _fmt_big(g["total_mcap_usd"]), 42, TEXT, bold=True),
        _arrow("up" if chg >= 0 else "down", 40, 172),
        _text(72, 192, f"{chg:+.2f}% за 24 год", 22, chg_color),
        # --- Панель Fear & Greed ---
        f'<rect x="610" y="84" width="260" height="200" rx="12" fill="{PANEL}"/>',
        _text(740, 114, "ІНДЕКС СТРАХУ І ЖАДІБНОСТІ", 13, MUTED, anchor="middle"),
        _gauge(fng["value"], 740, 220, 70, fng_col),
        _text(740, 258, fng["label"], 17, fng_col, bold=True, anchor="middle"),
    ]

    # --- Ряд метрик ---
    tiles = [
        ("Обсяг торгів 24г", _fmt_big(g["total_volume_usd"]), TEXT),
        ("Домінація BTC", f'{g["btc_dominance_pct"]:.1f}%', YELLOW),
        ("Домінація ETH", f'{g["eth_dominance_pct"]:.1f}%', BLUE),
        ("Монет у базі", f'{g["active_coins"]:,}', TEXT),
    ]
    bx, by, gap = 30, 300, 10
    bw = (W - 2 * bx - 3 * gap) / 4
    for i, (label, value, col) in enumerate(tiles):
        parts.append(_tile(bx + i * (bw + gap), by, bw, 80, label, value, col))

    parts += [
        _text(40, H - 18, f"Оновлено: {time_str}", 15, MUTED),
        "</svg>",
    ]
    return "".join(parts)


# ===========================================================================
# Картка 4: топ зростання / падіння
# ===========================================================================

def build_movers_svg(gainers: list, losers: list, time_str: str) -> str:
    """Картка топ-руху за 24 години 900x560: дві колонки по 5 монет."""
    H = 560
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        _text(40, 56, "Топ руху за 24 години (топ-100 монет)", 30, TEXT, bold=True),
    ]

    def column(x, title, title_col, rows):
        out = [
            f'<rect x="{x}" y="84" width="410" height="420" rx="12" fill="{PANEL}"/>',
            _text(x + 20, 118, title, 19, title_col, bold=True),
        ]
        y = 160
        for r in rows:
            ccol = GREEN if r["change_24h_pct"] >= 0 else RED
            out += [
                _text(x + 20, y, r["symbol"][:7], 18, TEXT, bold=True),
                _text(x + 130, y, r["name"][:15], 15, MUTED),
                _text(x + 390, y - 18, f'{r["change_24h_pct"]:+.2f}%', 17, ccol,
                      bold=True, anchor="end"),
                _text(x + 390, y + 2, _fmt_price(r["price"]), 14, MUTED,
                      anchor="end"),
            ]
            y += 70
        return out

    parts += column(30, "ЗРОСТАННЯ", GREEN, gainers)
    parts += column(460, "ПАДІННЯ", RED, losers)
    parts += [
        _text(40, H - 18, f"Оновлено: {time_str}", 15, MUTED),
        "</svg>",
    ]
    return "".join(parts)


# ===========================================================================
# Картка 5: цінове сповіщення
# ===========================================================================

def build_alert_svg(symbol: str, name: str, ref_price: float,
                    current_price: float, change_pct: float,
                    threshold_pct: float, time_str: str) -> str:
    """Картка сповіщення 900x300."""
    H = 300
    up = change_pct >= 0
    col = GREEN if up else RED
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<rect x="20" y="20" width="{W - 40}" height="{H - 40}" rx="16" '
        f'fill="{PANEL}" stroke="{col}" stroke-width="3"/>',
        _text(50, 78, "ЦІНОВЕ СПОВІЩЕННЯ", 16, MUTED),
        _text(50, 120, f"{name} ({symbol})", 30, TEXT, bold=True),
        _arrow("up" if up else "down", 50, 142, 26),
        _text(90, 164, f"{change_pct:+.2f}%", 30, col, bold=True),
        _text(50, 210, f"Було: {_fmt_price(ref_price)}", 19, MUTED),
        _text(50, 240, f"Стало: {_fmt_price(current_price)}", 19, TEXT, bold=True),
        _text(850, 210, f"Ваш поріг: {threshold_pct}%", 17, MUTED, anchor="end"),
        _text(850, 240, time_str, 17, MUTED, anchor="end"),
        "</svg>",
    ]
    return "".join(parts)


# ===========================================================================
# Конвертація SVG -> PNG
# ===========================================================================

def svg_to_png_bytes(svg_text: str, scale: float = 1.5) -> bytes:
    """
    Конвертує SVG у PNG (bytes) для відправки фото в Telegram.

    Спершу пробує cairosvg (якщо встановлений і системна cairo доступна),
    інакше використовує вбудований растеризатор на Pillow — він працює
    на Windows одразу, без додаткових бібліотек.
    """
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), scale=scale)
    except (ImportError, OSError):
        from pil_raster import rasterize

        return rasterize(svg_text, scale=scale)
