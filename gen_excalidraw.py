# -*- coding: utf-8 -*-
"""Generate a pretty Excalidraw scene for Crypto Risk Bot architecture."""
import json, random, os

random.seed(7)
def nonce(): return random.randint(1, 2_000_000_000)

elements = []

BASE = dict(
    isDeleted=False, fillStyle="solid", strokeStyle="solid",
    roughness=1, opacity=100, angle=0, groupIds=[], frameId=None,
    boundElements=[], updated=1, link=None, locked=False,
)

def rect(id, x, y, w, h, bg="#ffffff", stroke="#1e1e1e", sw=2, round=True, dash=False):
    e = dict(BASE)
    e.update(
        type="rectangle", id=id, version=1, versionNonce=nonce(), seed=nonce(),
        x=x, y=y, width=w, height=h, strokeColor=stroke, backgroundColor=bg,
        strokeWidth=sw, fillStyle="solid",
        strokeStyle="dashed" if dash else "solid",
        roundness={"type": 3} if round else None, boundElements=[],
    )
    elements.append(e)
    return e

def text(id, x, y, w, h, s, size=16, color="#1e1e1e", align="center",
         valign="middle", container=None, font=2, bold_seed=False):
    e = dict(BASE)
    e.update(
        type="text", id=id, version=1, versionNonce=nonce(), seed=nonce(),
        x=x, y=y, width=w, height=h, strokeColor=color, backgroundColor="transparent",
        strokeWidth=2, text=s, fontSize=size, fontFamily=font,
        textAlign=align, verticalAlign=valign, baseline=int(h*0.7),
        containerId=container, originalText=s, lineHeight=1.25,
        autoResize=True,
    )
    elements.append(e)
    return e

def labeled(id, x, y, w, h, label, bg, stroke="#1e1e1e", size=16, sw=2,
            color="#1e1e1e", round=True, dash=False, font=2):
    r = rect(id, x, y, w, h, bg=bg, stroke=stroke, sw=sw, round=round, dash=dash)
    t = text(id + "_t", x, y, w, h, label, size=size, color=color,
             container=id, font=font)
    r["boundElements"] = [{"type": "text", "id": id + "_t"}]
    return r

def arrow(id, x1, y1, x2, y2, start=None, end=None, color="#495057", sw=2,
          dashed=False, bidi=False, label=None):
    e = dict(BASE)
    e.update(
        type="arrow", id=id, version=1, versionNonce=nonce(), seed=nonce(),
        x=x1, y=y1, width=abs(x2 - x1), height=abs(y2 - y1),
        strokeColor=color, backgroundColor="transparent", strokeWidth=sw,
        strokeStyle="dashed" if dashed else "solid",
        points=[[0, 0], [x2 - x1, y2 - y1]],
        startArrowhead="arrow" if bidi else None, endArrowhead="arrow",
        startBinding={"elementId": start, "focus": 0, "gap": 6} if start else None,
        endBinding={"elementId": end, "focus": 0, "gap": 6} if end else None,
        roundness={"type": 2},
        elbowed=False,
    )
    elements.append(e)
    if label:
        text(id + "_lab", (x1 + x2) / 2 - 40, (y1 + y2) / 2 - 22, 80, 20,
             label, size=12, color=color)
    return e

def panel(prefix, x, y, w, title, items, panel_bg, title_bg, child_bg,
          stroke, child_stroke, emoji=""):
    titleH = 50
    itemH = 46
    gap = 14
    n = len(items)
    h = titleH + gap + n * (itemH + gap)
    # outer panel
    rect(prefix, x, y, w, h, bg=panel_bg, stroke=stroke, sw=2.5, round=True)
    # title bar
    labeled(prefix + "_title", x + 10, y + 10, w - 20, titleH - 6,
            (emoji + "  " if emoji else "") + title, bg=title_bg, stroke=stroke,
            size=18, sw=2, color="#1e1e1e")
    child_ids = []
    cy = y + titleH + gap
    for i, (cid, label) in enumerate(items):
        labeled(prefix + "_" + cid, x + 18, cy, w - 36, itemH, label,
                bg=child_bg, stroke=child_stroke, size=14.5, sw=1.5)
        child_ids.append(prefix + "_" + cid)
        cy += itemH + gap
    return dict(id=prefix, x=x, y=y, w=w, h=h, children=child_ids,
                title=prefix + "_title")

# ---------------- TITLE ----------------
text("title", 80, 24, 900, 50, "Crypto Risk Bot  —  Architecture", size=34,
     color="#1971c2", align="left")
text("subtitle", 84, 74, 1000, 30,
     "Telegram bot · aiogram 3 · risk scoring · charts · on-chain safety · signals · Stars",
     size=15, color="#868e96", align="left")

# ---------------- COLUMN 1: request spine ----------------
c1x, c1w = 120, 330

user = labeled("user", c1x + 35, 150, c1w - 70, 70,
               "👤  User", bg="#ffec99", stroke="#f08c00", size=20, sw=2.5)
tg = labeled("tg", c1x + 35, 268, c1w - 70, 70,
             "✈️  Telegram  Bot API", bg="#99e9f2", stroke="#0c8599", size=18, sw=2.5)

app = panel("app", c1x, 390, c1w, "app/  ·  Bot core",
            [("main", "main · handlers · keyboards"),
             ("alerts", "alerts · rules + bg loop"),
             ("payments", "payments · Telegram Stars ⭐"),
             ("ratelimit", "ratelimit · middleware")],
            panel_bg="#e7f5ff", title_bg="#a5d8ff", child_bg="#ffffff",
            stroke="#1971c2", child_stroke="#4dabf7", emoji="🧠")

core_y = app["y"] + app["h"] + 60
core = panel("core", c1x, core_y, c1w, "core/  ·  Infrastructure",
             [("settings", "settings · .env"),
              ("db", "db · async SQLite"),
              ("cache", "cache · Redis / memory"),
              ("storage", "storage · favorites.json"),
              ("i18n", "i18n · uk / en")],
             panel_bg="#f3f0ff", title_bg="#d0bfff", child_bg="#ffffff",
             stroke="#7048e8", child_stroke="#9775fa", emoji="⚙️")

# ---------------- COLUMN 2: processing ----------------
c2x, c2w = 560, 350

sources = panel("src", c2x, 150, c2w, "sources/  ·  Data providers",
                [("market", "market_data · CoinGecko / OKX"),
                 ("onchain", "onchain · GoPlus + honeypot.is"),
                 ("deriv", "derivatives · OKX"),
                 ("news", "news · RSS / CryptoPanic")],
                panel_bg="#ebfbee", title_bg="#b2f2bb", child_bg="#ffffff",
                stroke="#2f9e44", child_stroke="#69db7c", emoji="🌐")

an_y = sources["y"] + sources["h"] + 50
analytics = panel("an", c2x, an_y, c2w, "analytics/  ·  Brains",
                  [("analysis", "analysis · risk score · RSI · ATR"),
                   ("indicators", "indicators · MACD · Bollinger"),
                   ("signals", "signals · LONG / SHORT"),
                   ("backtest", "backtest · EMA / RSI strategies"),
                   ("portfolio", "portfolio · P&L · allocation"),
                   ("ai", "ai · OpenAI helper 🤖")],
                  panel_bg="#fff4e6", title_bg="#ffd8a8", child_bg="#ffffff",
                  stroke="#e8590c", child_stroke="#ffa94d", emoji="📊")

render_y = analytics["y"] + analytics["h"] + 50
render = panel("rnd", c2x, render_y, c2w, "render/  ·  Visual cards",
               [("svg", "svg_render · SVG cards"),
                ("pil", "pil_raster · SVG → PNG"),
                ("cards", "cards · layout")],
               panel_bg="#fff0f6", title_bg="#fcc2d7", child_bg="#ffffff",
               stroke="#c2255c", child_stroke="#f783ac", emoji="🎨")

# ---------------- COLUMN 3: external services ----------------
c3x, c3w = 980, 250
ext = [
    ("coingecko", "🦎  CoinGecko"),
    ("okx", "🅾️  OKX"),
    ("goplus", "🛡️  GoPlus"),
    ("honeypot", "🍯  honeypot.is"),
    ("cpanic", "📰  CryptoPanic / RSS"),
    ("openai", "🤖  OpenAI API"),
    ("redis", "🟥  Redis"),
    ("sentry", "🛰️  Sentry"),
]
ext_ids = {}
ey = 150
text("ext_h", c3x, ey - 38, c3w, 26, "External services", size=18,
     color="#868e96", align="center")
for cid, label in ext:
    labeled("ext_" + cid, c3x, ey, c3w, 52, label, bg="#f1f3f5",
            stroke="#adb5bd", size=15, sw=2, dash=True)
    ext_ids[cid] = "ext_" + cid
    ey += 66

# ---------------- ARROWS ----------------
# spine
arrow("a_user_tg", user["x"] + user["width"]/2, user["y"] + user["height"],
      tg["x"] + tg["width"]/2, tg["y"], start="user", end="tg",
      color="#f08c00", sw=2.5)
arrow("a_tg_app", tg["x"] + tg["width"]/2, tg["y"] + tg["height"],
      app["x"] + app["w"]/2, app["y"], start="tg", end="app",
      color="#0c8599", sw=2.5, bidi=True)
arrow("a_app_core", app["x"] + app["w"]/2, app["y"] + app["h"],
      core["x"] + core["w"]/2, core["y"], start="app", end="core",
      color="#7048e8", sw=2.5, label="state")

# app -> sources / analytics / render
arrow("a_app_src", app["x"] + app["w"], app["y"] + 80,
      sources["x"], sources["y"] + 110, start="app", end="src",
      color="#2f9e44", sw=2.5, label="fetch")
arrow("a_app_an", app["x"] + app["w"], app["y"] + 150,
      analytics["x"], analytics["y"] + 120, start="app", end="an",
      color="#e8590c", sw=2.5, label="compute")
arrow("a_app_rnd", app["x"] + app["w"], app["y"] + 210,
      render["x"], render["y"] + 70, start="app", end="rnd",
      color="#c2255c", sw=2.5, label="draw")

# sources feed analytics
arrow("a_src_an", sources["x"] + sources["w"]/2, sources["y"] + sources["h"],
      analytics["x"] + analytics["w"]/2, analytics["y"],
      start="src", end="an", color="#2f9e44", sw=2, dashed=True)
# analytics -> render
arrow("a_an_rnd", analytics["x"] + analytics["w"]/2, analytics["y"] + analytics["h"],
      render["x"] + render["w"]/2, render["y"],
      start="an", end="rnd", color="#e8590c", sw=2, dashed=True)
# render -> telegram (PNG back)
arrow("a_rnd_tg", render["x"], render["y"] + 40,
      tg["x"] + tg["width"], tg["y"] + tg["height"]/2,
      start="rnd", end="tg", color="#c2255c", sw=2, dashed=True, label="PNG card")

# sources -> external
def ext_arrow(idp, src_id, src_el, sy, ext_key, color):
    e = ext_ids[ext_key]
    eel = next(x for x in elements if x["id"] == e)
    arrow(idp, src_el["x"] + src_el["w"], sy, eel["x"], eel["y"] + eel["height"]/2,
          start=src_el["id"], end=e, color=color, sw=1.5, dashed=True)

ext_arrow("e_cg", "src", sources, sources["y"] + 95, "coingecko", "#2f9e44")
ext_arrow("e_okx", "src", sources, sources["y"] + 95, "okx", "#2f9e44")
ext_arrow("e_gp", "src", sources, sources["y"] + 155, "goplus", "#2f9e44")
ext_arrow("e_hp", "src", sources, sources["y"] + 155, "honeypot", "#2f9e44")
ext_arrow("e_cp", "src", sources, sources["y"] + 270, "cpanic", "#2f9e44")
# analytics ai -> openai
oa = next(x for x in elements if x["id"] == ext_ids["openai"])
arrow("e_oa", analytics["x"] + analytics["w"], analytics["y"] + analytics["h"] - 40,
      oa["x"], oa["y"] + oa["height"]/2, start="an", end=ext_ids["openai"],
      color="#e8590c", sw=1.5, dashed=True)
# core cache -> redis
rd = next(x for x in elements if x["id"] == ext_ids["redis"])
arrow("e_rd", core["x"] + core["w"], core_y + 150, rd["x"], rd["y"] + rd["height"]/2,
      start="core", end=ext_ids["redis"], color="#7048e8", sw=1.5, dashed=True)
# app -> sentry
se = next(x for x in elements if x["id"] == ext_ids["sentry"])
arrow("e_se", app["x"] + app["w"], app["y"] + app["h"] - 20,
      se["x"], se["y"] + se["height"]/2, start="app", end=ext_ids["sentry"],
      color="#868e96", sw=1.5, dashed=True, label="errors")

# ---------------- legend ----------------
ly = render["y"] + render["h"] + 50
labeled("leg", c1x, ly, 760, 70,
        "Flow:  User → Telegram → app(core) → sources → analytics → render → PNG back to Telegram\n"
        "Solid = control · Dashed = data / external calls",
        bg="#ffffff", stroke="#ced4da", size=14, sw=1.5)

scene = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": elements,
    "appState": {"gridSize": None, "viewBackgroundColor": "#fbfbfb"},
    "files": {},
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "crypto_risk_bot_architecture.excalidraw")
with open(out, "w", encoding="utf-8") as f:
    json.dump(scene, f, ensure_ascii=False, indent=2)
print("written:", out, "elements:", len(elements))
