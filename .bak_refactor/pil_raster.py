"""
Мінімальний растеризатор SVG -> PNG на Pillow.

Працює на Windows / Linux / macOS без жодних системних бібліотек
(потрібен лише пакет pillow). Підтримує підмножину SVG, яку генерує
svg_render.py: rect, text, polygon, polyline, path (дуги), кольори, opacity.
"""

import io
import math
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

# Кандидати шрифтів: спочатку Windows (Arial), потім Linux (DejaVu)
FONT_REGULAR = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
FONT_BOLD = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]

_font_cache = {}


def _load_font(size: int, bold: bool):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    for name in (FONT_BOLD if bold else FONT_REGULAR):
        try:
            f = ImageFont.truetype(name, size)
            _font_cache[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _f(el, attr, default=0.0):
    v = el.get(attr)
    return float(v) if v not in (None, "") else default


def _color(value, opacity=1.0):
    """#rrggbb -> (r, g, b, a)"""
    if not value or value == "none":
        return None
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r, g, b, int(255 * opacity))
    named = {"white": (255, 255, 255), "black": (0, 0, 0)}
    if value in named:
        r, g, b = named[value]
        return (r, g, b, int(255 * opacity))
    return (0, 0, 0, int(255 * opacity))


def _points(el, k):
    pts = []
    for pair in el.get("points", "").split():
        x, y = pair.split(",")
        pts.append((float(x) * k, float(y) * k))
    return pts


def _arc_center(x1, y1, x2, y2, r, large, sweep):
    """Перетворення endpoint -> center для кругової дуги (SVG spec F.6.5)."""
    x1p, y1p = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    lam = x1p * x1p + y1p * y1p
    if lam > r * r:
        r = math.sqrt(lam)
    co = math.sqrt(max(0.0, (r * r - lam) / lam)) if lam else 0.0
    sign = -1.0 if large == sweep else 1.0
    cxp, cyp = sign * co * y1p, -sign * co * x1p
    cx, cy = cxp + (x1 + x2) / 2.0, cyp + (y1 + y2) / 2.0
    a1 = math.degrees(math.atan2(y1 - cy, x1 - cx)) % 360
    a2 = math.degrees(math.atan2(y2 - cy, x2 - cx)) % 360
    return cx, cy, r, a1, a2


_PATH_RE = re.compile(
    r"M\s*([\d.+-]+)\s+([\d.+-]+)\s*A\s*([\d.+-]+)\s+([\d.+-]+)\s+[\d.+-]+\s+"
    r"([01])\s+([01])\s+([\d.+-]+)\s+([\d.+-]+)"
)


def _draw_path(draw, el, k):
    """Підтримуються шляхи вигляду 'M x y A r r 0 large sweep x y' (дуги шкали)."""
    d = el.get("d", "")
    m = _PATH_RE.search(d)
    if not m:
        return
    x1, y1, r1, _, large, sweep, x2, y2 = (
        float(m.group(1)), float(m.group(2)), float(m.group(3)),
        float(m.group(4)), int(m.group(5)), int(m.group(6)),
        float(m.group(7)), float(m.group(8)),
    )
    x1, y1, x2, y2, r1 = x1 * k, y1 * k, x2 * k, y2 * k, r1 * k
    stroke = _color(el.get("stroke"))
    width = max(1, round(_f(el, "stroke-width", 1.0) * k))
    cx, cy, r, a1, a2 = _arc_center(x1, y1, x2, y2, r1, large, sweep)
    if sweep == 0:
        a1, a2 = a2, a1
    if a2 < a1:
        a2 += 360
    bbox = [cx - r, cy - r, cx + r, cy + r]
    draw.arc(bbox, start=a1, end=a2, fill=stroke, width=width)
    if el.get("stroke-linecap") == "round":
        for ang in (a1, a2):
            ex = cx + r * math.cos(math.radians(ang))
            ey = cy + r * math.sin(math.radians(ang))
            rr = width / 2.0
            draw.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=stroke)


def rasterize(svg_text: str, scale: float = 1.5, supersample: int = 2) -> bytes:
    """Рендерить SVG-рядок у PNG (bytes)."""
    root = ET.fromstring(svg_text)
    w = int(float(root.get("width")))
    h = int(float(root.get("height")))
    k = scale * supersample  # коефіцієнт усіх координат

    img = Image.new("RGBA", (int(w * k), int(h * k)), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag == "rect":
            x, y = _f(el, "x") * k, _f(el, "y") * k
            rw, rh = _f(el, "width") * k, _f(el, "height") * k
            rx = _f(el, "rx") * k
            fill = _color(el.get("fill"))
            stroke = _color(el.get("stroke"))
            sw = max(1, round(_f(el, "stroke-width", 1.0) * k)) if stroke else 0
            draw.rounded_rectangle(
                [x, y, x + rw, y + rh], radius=rx,
                fill=fill, outline=stroke, width=sw,
            )
        elif tag == "polygon":
            pts = _points(el, k)
            opacity = _f(el, "opacity", 1.0)
            fill = _color(el.get("fill"), opacity)
            if opacity < 1.0:
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                ImageDraw.Draw(layer).polygon(pts, fill=fill)
                img.alpha_composite(layer)
                draw = ImageDraw.Draw(img)
            else:
                draw.polygon(pts, fill=fill)
        elif tag == "polyline":
            pts = _points(el, k)
            stroke = _color(el.get("stroke"))
            width = max(1, round(_f(el, "stroke-width", 1.0) * k))
            draw.line(pts, fill=stroke, width=width, joint="curve")
        elif tag == "path":
            _draw_path(draw, el, k)
        elif tag == "text":
            x, y = _f(el, "x") * k, _f(el, "y") * k
            size = max(6, round(_f(el, "font-size", 16.0) * k))
            bold = el.get("font-weight") == "bold"
            fill = _color(el.get("fill"))
            anchor = {"middle": "ms", "end": "rs"}.get(
                el.get("text-anchor"), "ls"
            )
            font = _load_font(size, bold)
            try:
                draw.text((x, y), el.text or "", font=font, fill=fill, anchor=anchor)
            except (ValueError, TypeError):
                # bitmap-шрифт без anchor: ручне вирівнювання
                tw = draw.textlength(el.text or "", font=font)
                ox = x - tw / 2 if anchor == "ms" else (x - tw if anchor == "rs" else x)
                draw.text((ox, y - size), el.text or "", font=font, fill=fill)

    if supersample > 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
