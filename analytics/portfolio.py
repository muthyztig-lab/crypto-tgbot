from core import db
from sources.market_data import get_simple_prices


async def compute(user_id: int) -> dict:
    """Збирає портфель користувача та рахує P&L/алокацію."""
    holdings = await db.list_holdings(user_id)
    if not holdings:
        return {"empty": True, "positions": [], "total_value": 0.0,
                "total_cost": 0.0, "total_pnl": 0.0, "total_pnl_pct": 0.0}

    coin_ids = list({h["coin_id"] for h in holdings})
    prices = get_simple_prices(coin_ids)

    positions, total_value, total_cost = [], 0.0, 0.0
    for h in holdings:
        price = prices.get(h["coin_id"], 0.0)
        value = price * h["amount"]
        cost = (h["buy_price"] or 0.0) * h["amount"]
        pnl = value - cost if cost else 0.0
        pnl_pct = (pnl / cost * 100) if cost else 0.0
        total_value += value
        total_cost += cost
        positions.append({
            "id": h["id"], "symbol": h["symbol"], "amount": h["amount"],
            "buy_price": h["buy_price"], "price": price, "value": value,
            "pnl": pnl, "pnl_pct": pnl_pct,
        })

    for p in positions:
        p["alloc_pct"] = (p["value"] / total_value * 100) if total_value else 0.0
    positions.sort(key=lambda p: p["value"], reverse=True)

    total_pnl = total_value - total_cost
    return {
        "empty": False,
        "positions": positions,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_pct": (total_pnl / total_cost * 100) if total_cost else 0.0,
    }
