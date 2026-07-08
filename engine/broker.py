from dataclasses import dataclass

from exchange import binance
from core import settings


@dataclass
class Fill:
    side: str
    qty: float
    ref_price: float
    exec_price: float
    fee: float
    slippage_bps: float


class PaperBroker:
    mode = "paper"

    def __init__(self, fee_bps: float, slippage_bps: float):
        self.fee = fee_bps / 10_000
        self.slip_bps = slippage_bps
        self.slip = slippage_bps / 10_000

    def buy(self, symbol, cash, ref_price) -> Fill:
        exec_price = ref_price * (1 + self.slip)
        fee_cost = cash * self.fee
        qty = (cash - fee_cost) / exec_price
        return Fill("BUY", qty, ref_price, exec_price, fee_cost, self.slip_bps)

    def sell(self, symbol, qty, ref_price) -> Fill:
        exec_price = ref_price * (1 - self.slip)
        fee_cost = qty * exec_price * self.fee
        return Fill("SELL", qty, ref_price, exec_price, fee_cost, self.slip_bps)


class LiveBroker:
    mode = "live"

    def __init__(self, fee_bps: float, slippage_bps: float):
        self.slip_bps = slippage_bps

    def buy(self, symbol, cash, ref_price) -> Fill:
        qty = (cash / ref_price) * 0.999
        r = binance.market_order(symbol, "BUY", qty)
        exec_price = r.get("_avg_price") or ref_price
        return Fill("BUY", r.get("_filled_qty", qty), ref_price, exec_price,
                    _fee_quote(r, exec_price),
                    _slip_bps(ref_price, exec_price, "BUY"))

    def sell(self, symbol, qty, ref_price) -> Fill:
        r = binance.market_order(symbol, "SELL", qty)
        exec_price = r.get("_avg_price") or ref_price
        return Fill("SELL", r.get("_filled_qty", qty), ref_price, exec_price,
                    _fee_quote(r, exec_price),
                    _slip_bps(ref_price, exec_price, "SELL"))


def _fee_quote(order, price):
    return order.get("_fee", 0.0) * price


def _slip_bps(ref, exec_price, side):
    if not ref:
        return 0.0
    diff = (exec_price - ref) / ref if side == "BUY" else (ref - exec_price) / ref
    return round(diff * 10_000, 2)


def make_broker(mode: str, fee_bps: float, slippage_bps: float):
    if mode == "live" and settings.can_trade_live():
        return LiveBroker(fee_bps, slippage_bps)
    return PaperBroker(fee_bps, slippage_bps)
