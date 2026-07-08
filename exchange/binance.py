import time
import math
import hmac
import hashlib
import urllib.parse

import requests

from core import settings

PUBLIC_BASE = "https://api.binance.com"
TESTNET_BASE = "https://testnet.binance.vision"

INTERVALS = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}

BARS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040,
    "1h": 8_760, "4h": 2_190, "1d": 365,
}

_HEADERS = {"User-Agent": "AlgoTradeBot/1.0"}
_SESSION = requests.Session()


class ExchangeError(Exception):
    pass


def _trade_base() -> str:
    return TESTNET_BASE if settings.BINANCE_TESTNET else PUBLIC_BASE


def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
    if not s.endswith(("USDT", "USDC", "BUSD")):
        s += "USDT"
    return s


def fetch_klines(symbol: str, interval: str, limit: int = 500,
                 end_ms: int | None = None, testnet: bool = False) -> list:
    iv = INTERVALS.get(interval)
    if not iv:
        raise ExchangeError(f"Невідомий таймфрейм: {interval}")
    base = TESTNET_BASE if testnet else PUBLIC_BASE
    params = {"symbol": normalize_symbol(symbol), "interval": iv,
              "limit": min(max(limit, 1), 1000)}
    if end_ms:
        params["endTime"] = int(end_ms)
    try:
        r = _SESSION.get(f"{base}/api/v3/klines", params=params,
                         headers=_HEADERS, timeout=15)
        if r.status_code == 400:
            raise ExchangeError(
                f"Пари {normalize_symbol(symbol)} немає на Binance"
                f"{' (testnet)' if testnet else ''}.")
        r.raise_for_status()
        rows = r.json()
    except requests.RequestException as e:
        raise ExchangeError(f"Binance недоступний: {e}") from e
    return [
        {"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
         "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
         "close_ms": int(k[6])}
        for k in rows
    ]


def fetch_price(symbol: str, testnet: bool = False) -> float:
    base = TESTNET_BASE if testnet else PUBLIC_BASE
    try:
        r = _SESSION.get(f"{base}/api/v3/ticker/price",
                         params={"symbol": normalize_symbol(symbol)},
                         headers=_HEADERS, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except (requests.RequestException, KeyError, ValueError) as e:
        raise ExchangeError(f"Не вдалося отримати ціну: {e}") from e


_EXINFO: dict = {}


def _exchange_info(symbol: str) -> dict:
    s = normalize_symbol(symbol)
    if s in _EXINFO:
        return _EXINFO[s]
    info = {"step": 0.0, "min_qty": 0.0, "min_notional": 0.0}
    try:
        r = _SESSION.get(f"{_trade_base()}/api/v3/exchangeInfo",
                         params={"symbol": s}, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        sym = r.json()["symbols"][0]
        for f in sym["filters"]:
            if f["filterType"] == "LOT_SIZE":
                info["step"] = float(f["stepSize"])
                info["min_qty"] = float(f["minQty"])
            elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                info["min_notional"] = float(f.get("minNotional")
                                             or f.get("notional") or 0)
    except Exception:
        pass
    _EXINFO[s] = info
    return info


def round_qty(symbol: str, qty: float) -> float:
    step = _exchange_info(symbol)["step"]
    if step and step > 0:
        qty = math.floor(qty / step) * step
        decimals = max(0, round(-math.log10(step))) if step < 1 else 0
        return round(qty, decimals)
    return qty


def _signed_request(method: str, path: str, params: dict) -> dict:
    if not (settings.BINANCE_API_KEY and settings.BINANCE_API_SECRET):
        raise ExchangeError("Немає ключів Binance для live-режиму "
                            "(BINANCE_API_KEY / BINANCE_API_SECRET у .env).")
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        settings.BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256,
    ).hexdigest()
    url = f"{_trade_base()}{path}?{query}&signature={signature}"
    headers = {**_HEADERS, "X-MBX-APIKEY": settings.BINANCE_API_KEY}
    try:
        r = _SESSION.request(method, url, headers=headers, timeout=15)
        data = r.json()
    except requests.RequestException as e:
        raise ExchangeError(f"Binance API помилка: {e}") from e
    if isinstance(data, dict) and data.get("code", 0) and data.get("code") != 200:
        raise ExchangeError(f"Binance: {data.get('msg', data)}")
    return data


def account_balances() -> dict:
    data = _signed_request("GET", "/api/v3/account", {})
    return {b["asset"]: float(b["free"]) for b in data.get("balances", [])
            if float(b["free"]) > 0}


def market_order(symbol: str, side: str, quantity: float) -> dict:
    qty = round_qty(symbol, quantity)
    info = _exchange_info(symbol)
    if info["min_qty"] and qty < info["min_qty"]:
        raise ExchangeError(
            f"Кількість {qty} менша за мінімальну {info['min_qty']} для "
            f"{normalize_symbol(symbol)}. Збільш START_EQUITY у .env.")
    data = _signed_request("POST", "/api/v3/order", {
        "symbol": normalize_symbol(symbol),
        "side": side.upper(),
        "type": "MARKET",
        "quantity": f"{qty:.8f}".rstrip("0").rstrip("."),
    })
    fills = data.get("fills", [])
    if fills:
        filled = sum(float(f["qty"]) for f in fills)
        cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
        data["_avg_price"] = cost / filled if filled else 0.0
        data["_filled_qty"] = filled
        data["_fee"] = sum(float(f["commission"]) for f in fills)
    return data
