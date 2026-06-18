import html
from render.svg_render import (
    W, BG, PANEL, TEXT, MUTED, GREEN, RED, BLUE, YELLOW, ORANGE,
    _text, _fmt_price, _fmt_big, svg_to_png_bytes,
)

PAD = 30
ROW_H = 30


def _bar(x, y, w, h, frac, color, track="#2a323c"):
    """Горизонтальна смуга-прогрес (frac 0..1)."""
    frac = max(0.0, min(1.0, frac))
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{track}"/>'
        f'<rect x="{x}" y="{y}" width="{max(1,w*frac):.0f}" height="{h}" rx="{h/2}" fill="{color}"/>'
    )


def _score_color(score):
    if score < 20:
        return GREEN
    if score < 45:
        return YELLOW
    if score < 70:
        return ORANGE
    return RED


def build_kv_card(title, subtitle, sections, accent=BLUE, time_str=""):
    """
    sections: список dict:
      {"heading": str, "rows": [(label, value, color?), ...]}
      або {"heading": str, "lines": [str, ...], "color": "#.."}
    Повертає SVG-рядок.
    """
    parts = []
    y = PAD + 28
    parts.append(_text(PAD, y, title, 26, TEXT, bold=True))
    y += 30
    if subtitle:
        parts.append(_text(PAD, y, subtitle, 15, MUTED))
        y += 22
    parts.append(f'<rect x="{PAD}" y="{y}" width="{W-2*PAD}" height="3" fill="{accent}"/>')
    y += 22

    for sec in sections:
        if sec.get("heading"):
            parts.append(_text(PAD, y, sec["heading"], 16, accent, bold=True))
            y += 26
        for label, *rest in sec.get("rows", []):
            value = rest[0] if rest else ""
            color = rest[1] if len(rest) > 1 else TEXT
            parts.append(_text(PAD + 6, y, label, 15, MUTED))
            parts.append(_text(W - PAD, y, str(value), 15, color, bold=True, anchor="end"))
            y += ROW_H
        color = sec.get("color", TEXT)
        for line in sec.get("lines", []):
            parts.append(_text(PAD + 6, y, line, 14, color))
            y += 26
        y += 8

    if time_str:
        y += 4
        parts.append(_text(PAD, y, f"Оновлено: {time_str}", 12, MUTED))
        y += 10

    height = y + PAD
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}">'
        f'<rect width="{W}" height="{height}" fill="{BG}"/>'
        f'<rect x="12" y="12" width="{W-24}" height="{height-24}" rx="16" fill="{PANEL}"/>'
        + "".join(parts) + "</svg>"
    )
    return svg


def build_onchain_card(r: dict, time_str: str) -> str:
    color = _score_color(r["score"])
    sections = [{
        "heading": f"Rug-pull ризик: {r['score']:.0f}/100 — {r['category']}",
        "rows": [],
    }]
    sections[0]["rows"] = list(r["facts"])
    if r["reds"]:
        sections.append({"heading": "Критичні прапорці", "lines": r["reds"], "color": RED})
    if r["yellows"]:
        sections.append({"heading": "Застереження", "lines": r["yellows"], "color": YELLOW})
    if r["greens"]:
        sections.append({"heading": "Позитивні фактори", "lines": r["greens"], "color": GREEN})
    sub = f"{r['name']} ({r['symbol']}) · {r['chain'].upper()} · {r['address'][:10]}…{r['address'][-6:]}"
    return build_kv_card("On-chain перевірка токена", sub, sections, accent=color, time_str=time_str)


def build_derivatives_card(d: dict, time_str: str) -> str:
    f = d["funding_pct"]
    fcolor = GREEN if f > 0 else (RED if f < 0 else MUTED)
    ls = d["long_short_ratio"]
    lscolor = GREEN if ls > 1 else (RED if 0 < ls < 1 else TEXT)
    sections = [{
        "heading": "Ринок безстрокових ф'ючерсів (OKX)",
        "rows": [
            ("Funding rate (поточний)", f"{f:+.4f}%", fcolor),
            ("Open Interest", _fmt_big(d["oi_usd"])),
            ("Long/Short ratio", f"{ls:.2f}" if ls else "н/д", lscolor),
        ],
    }, {"heading": "Інтерпретація", "lines": d["notes"], "color": TEXT}]
    return build_kv_card(f"Деривативи {d['symbol']}", "Сентимент ф'ючерсного ринку",
                         sections, accent=BLUE, time_str=time_str)


def build_confluence_card(symbol: str, c: dict, time_str: str) -> str:
    score = c["score"]
    color = GREEN if score > 15 else (RED if score < -15 else YELLOW)
    rows = []
    for name, value, bias in c["signals"]:
        bc = GREEN if "лонг" in bias else (RED if "шорт" in bias else MUTED)
        rows.append((f"{name}: {value}", bias, bc))
    sections = [
        {"heading": f"Конфлюенс: {score:+.0f} → {c['verdict']}", "rows": rows},
    ]
    return build_kv_card(f"Технічні сигнали {symbol}",
                         "MACD · Bollinger · RSI · EMA · дивергенція",
                         sections, accent=color, time_str=time_str)


def build_backtest_card(symbol: str, bt: dict, time_str: str) -> str:
    def strat_rows(s):
        wc = GREEN if s["win_rate"] >= 50 else RED
        tc = GREEN if s["total_return_pct"] >= 0 else RED
        return [
            ("Угод", str(s["trades"])),
            ("Win-rate", f"{s['win_rate']}%", wc),
            ("Дохідність", f"{s['total_return_pct']:+.2f}%", tc),
            ("Серед. угода", f"{s['avg_trade_pct']:+.2f}%"),
            ("Max drawdown", f"-{s['max_dd_pct']}%", RED),
        ]
    bh = bt["buy_hold_pct"]
    sections = [
        {"heading": "Стратегія EMA 12/48 кросовер", "rows": strat_rows(bt["ema_cross"])},
        {"heading": "Стратегія RSI 30/70", "rows": strat_rows(bt["rsi"])},
        {"heading": "Орієнтир", "rows": [
            ("Buy & Hold", f"{bh:+.2f}%", GREEN if bh >= 0 else RED),
            ("Барів у тесті", str(bt["bars"])),
        ]},
    ]
    return build_kv_card(f"Бектест {symbol}", "Історична перевірка стратегій (не прогноз)",
                         sections, accent=BLUE, time_str=time_str)


def build_portfolio_card(p: dict, time_str: str) -> str:
    rows = []
    for pos in p["positions"]:
        pc = GREEN if pos["pnl"] >= 0 else RED
        rows.append((
            f"{pos['symbol']} · {pos['amount']:g} @ {_fmt_price(pos['buy_price'])} · {pos['alloc_pct']:.0f}%",
            f"{_fmt_price(pos['value'])} ({pos['pnl_pct']:+.1f}%)", pc,
        ))
    tcolor = GREEN if p["total_pnl"] >= 0 else RED
    sections = [
        {"heading": "Позиції", "rows": rows},
        {"heading": "Підсумок", "rows": [
            ("Вартість", _fmt_price(p["total_value"])),
            ("Вкладено", _fmt_price(p["total_cost"])),
            ("P&L", f"{_fmt_price(p['total_pnl'])} ({p['total_pnl_pct']:+.1f}%)", tcolor),
        ]},
    ]
    return build_kv_card("Портфель", "Ручний облік позицій", sections,
                         accent=tcolor, time_str=time_str)


def build_news_card(n: dict, time_str: str) -> str:
    scolor = {"позитивний": GREEN, "негативний": RED}.get(n["sentiment"], YELLOW)
    lines = []
    for it in n["items"]:
        title = it["title"]
        if len(title) > 84:
            title = title[:81] + "…"
        lines.append("• " + title)
    sub = f"Сентимент: {n['sentiment']} (бал {n['score']:+d})"
    if n.get("currency"):
        sub = f"{n['currency']} · " + sub
    sections = [{"heading": "Останні заголовки", "lines": lines or ["Новини недоступні"], "color": TEXT}]
    return build_kv_card("Крипто-новини", sub, sections, accent=scolor, time_str=time_str)
