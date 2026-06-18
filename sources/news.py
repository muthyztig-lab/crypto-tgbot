import re
import html
import logging
from urllib.request import urlopen, Request

from core import settings
from core import cache

CRYPTOPANIC = "https://cryptopanic.com/api/v1/posts/"
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

_POS = ["surge", "rally", "soar", "gain", "bull", "record", "high", "approve",
        "adopt", "partnership", "upgrade", "breakout", "support"]
_NEG = ["crash", "plunge", "drop", "fall", "bear", "hack", "exploit", "ban",
        "lawsuit", "sec", "sell-off", "dump", "liquidation", "fraud", "scam"]


def _sentiment(text: str) -> int:
    t = text.lower()
    pos = sum(t.count(w) for w in _POS)
    neg = sum(t.count(w) for w in _NEG)
    return pos - neg


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _from_rss(limit: int) -> list:
    items = []
    for url in RSS_FEEDS:
        try:
            req = Request(url, headers={"User-Agent": "CryptoRiskBot/4.0"})
            raw = urlopen(req, timeout=12).read().decode("utf-8", "ignore")
            blocks = re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", raw, re.S)
            for block in blocks[:limit]:
                tm = re.search(r"<title>(.*?)</title>", block, re.S)
                lm = re.search(r'<link[^>]*?href="([^"]+)"', block) or \
                    re.search(r"<link>(.*?)</link>", block, re.S)
                t = _strip_tags(tm.group(1)) if tm else ""
                if t:
                    items.append({"title": t,
                                  "url": (lm.group(1).strip() if lm else ""),
                                  "source": "RSS"})
        except Exception:
            logging.warning("RSS-стрічка недоступна: %s", url)
    return items


def _from_cryptopanic(currency: str, limit: int) -> list:
    if not settings.CRYPTOPANIC_API_KEY:
        return []

    def fetch():
        params = f"?auth_token={settings.CRYPTOPANIC_API_KEY}&public=true&kind=news"
        if currency:
            params += f"&currencies={currency.upper()}"
        import json
        req = Request(CRYPTOPANIC + params,
                      headers={"User-Agent": "CryptoRiskBot/4.0"})
        data = json.loads(urlopen(req, timeout=12).read().decode("utf-8", "ignore"))
        out = []
        for p in (data.get("results") or [])[:limit]:
            votes = p.get("votes") or {}
            out.append({"title": p.get("title", ""), "url": p.get("url", ""),
                        "source": "CryptoPanic",
                        "bullish": votes.get("positive", 0),
                        "bearish": votes.get("negative", 0)})
        return out

    try:
        return cache.cached(f"cp:{currency}", fetch, ttl=300)
    except Exception:
        logging.exception("CryptoPanic недоступний")
        return []


def get_news(currency: str = "", limit: int = 6) -> dict:
    """Повертає {items:[...], sentiment:'...', score:int}."""
    items = _from_cryptopanic(currency, limit) or cache.cached(
        "rss", lambda: _from_rss(limit), ttl=300)
    items = items[:limit]

    score = sum(_sentiment(i["title"]) for i in items)
    score += sum(i.get("bullish", 0) - i.get("bearish", 0) for i in items)
    if score >= 2:
        label = "позитивний"
    elif score <= -2:
        label = "негативний"
    else:
        label = "нейтральний"
    return {"items": items, "sentiment": label, "score": score,
            "currency": currency.upper()}
