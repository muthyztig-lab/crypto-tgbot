"""
БЛОК 1 — On-chain ризик-перевірка токена (головна фішка risk-бота).

Джерела (БЕЗ ключів):
- GoPlus Security API — honeypot, податки, права власника, mint/pause,
  концентрація холдерів, блокування ліквідності тощо.
- honeypot.is — додаткова перевірка honeypot/симуляція купівлі-продажу (EVM).

Повертає структуровану картку ризику + власний скоринг 0..100 (rug-pull risk)
з переліком червоних/жовтих прапорців простою мовою.
"""

import requests
import cache

GOPLUS = "https://api.gopluslabs.io/api/v1/token_security"
HONEYPOT_IS = "https://api.honeypot.is/v2/IsHoneypot"
HEADERS = {"User-Agent": "CryptoRiskBot/4.0"}

# Назва -> chain_id для GoPlus
CHAINS = {
    "eth": "1", "ethereum": "1",
    "bsc": "56", "bnb": "56",
    "polygon": "137", "matic": "137",
    "arbitrum": "42161", "arb": "42161",
    "optimism": "10", "op": "10",
    "base": "8453",
    "avalanche": "43114", "avax": "43114",
    "fantom": "250", "ftm": "250",
}


class OnchainUnavailable(Exception):
    """Не вдалося перевірити токен (невідома мережа / адреса / API)."""


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _truthy(v) -> bool:
    return str(v) == "1"


def chain_id(chain: str) -> str:
    cid = CHAINS.get(chain.strip().lower())
    if not cid:
        raise OnchainUnavailable(
            f"Невідома мережа «{chain}». Доступні: {', '.join(sorted(set(CHAINS)))}."
        )
    return cid


def _goplus(cid: str, address: str) -> dict:
    def fetch():
        r = requests.get(f"{GOPLUS}/{cid}", params={"contract_addresses": address},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        j = r.json()
        return (j.get("result") or {}).get(address.lower(), {})
    return cache.cached(f"goplus:{cid}:{address.lower()}", fetch, ttl=300)


def _honeypot_is(cid: str, address: str) -> dict:
    """Лише EVM; повертає {} якщо недоступно."""
    chain_map = {"1": "1", "56": "56", "8453": "8453"}
    if cid not in chain_map:
        return {}

    def fetch():
        try:
            r = requests.get(HONEYPOT_IS,
                             params={"address": address, "chainID": cid},
                             headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}
    return cache.cached(f"honeypot:{cid}:{address.lower()}", fetch, ttl=300)


def token_security(chain: str, address: str) -> dict:
    """
    Головна функція. Повертає словник:
      name, symbol, chain, address,
      score (0..100, вище = ризикованіше), category,
      reds  — список критичних прапорців,
      yellows — список застережень,
      greens  — позитивні фактори,
      facts   — пари (назва, значення) для картки.
    """
    address = address.strip()
    if not (address.startswith("0x") and len(address) == 42):
        raise OnchainUnavailable(
            "Це схоже не на EVM-адресу. Приклад: 0x... (42 символи)."
        )
    cid = chain_id(chain)
    g = _goplus(cid, address)
    if not g:
        raise OnchainUnavailable(
            "GoPlus не знає цей токен (можливо, нова/неперевірена адреса "
            "або непідтримувана мережа)."
        )
    h = _honeypot_is(cid, address)

    reds, yellows, greens, facts = [], [], [], []
    score = 0.0

    buy_tax = _f(g.get("buy_tax")) * 100
    sell_tax = _f(g.get("sell_tax")) * 100
    holders = int(_f(g.get("holder_count")))
    name = g.get("token_name") or "?"
    symbol = (g.get("token_symbol") or "?").upper()

    # --- honeypot ------------------------------------------------------
    hp_goplus = _truthy(g.get("is_honeypot"))
    hp_is = bool((h.get("honeypotResult") or {}).get("isHoneypot"))
    if hp_goplus or hp_is:
        reds.append("✗ HONEYPOT — продати токен неможливо/заблоковано")
        score += 60

    # --- податки -------------------------------------------------------
    facts.append(("Податок купівлі", f"{buy_tax:.1f}%"))
    facts.append(("Податок продажу", f"{sell_tax:.1f}%"))
    if sell_tax >= 50 or buy_tax >= 50:
        reds.append(f"✗ Грабіжницький податок (buy {buy_tax:.0f}% / sell {sell_tax:.0f}%)")
        score += 25
    elif sell_tax >= 10 or buy_tax >= 10:
        yellows.append(f"⚠ Високий податок (buy {buy_tax:.0f}% / sell {sell_tax:.0f}%)")
        score += 10

    # --- контроль над контрактом --------------------------------------
    if _truthy(g.get("is_mintable")):
        yellows.append("⚠ Mintable — власник може випускати нові токени")
        score += 12
    if _truthy(g.get("can_take_back_ownership")):
        reds.append("✗ Власник може повернути собі контроль")
        score += 15
    if _truthy(g.get("hidden_owner")):
        reds.append("✗ Прихований власник")
        score += 15
    if _truthy(g.get("selfdestruct")):
        reds.append("✗ Контракт можна знищити (selfdestruct)")
        score += 15
    if _truthy(g.get("transfer_pausable")):
        yellows.append("⚠ Перекази можна призупинити (pausable)")
        score += 8
    if _truthy(g.get("cannot_sell_all")):
        yellows.append("⚠ Не можна продати весь баланс одразу")
        score += 8
    if _truthy(g.get("is_proxy")):
        yellows.append("⚠ Proxy-контракт — логіку можна змінити")
        score += 6

    # --- прозорість ----------------------------------------------------
    if _truthy(g.get("is_open_source")):
        greens.append("✓ Відкритий вихідний код")
    else:
        reds.append("✗ Код контракту закритий (не верифікований)")
        score += 12

    # --- ліквідність ---------------------------------------------------
    lp_holders = g.get("lp_holders") or []
    locked = 0.0
    for lp in lp_holders:
        if _truthy(lp.get("is_locked")):
            locked += _f(lp.get("percent"))
    if lp_holders:
        facts.append(("Ліквідність заблокована", f"{locked * 100:.0f}%"))
        if locked < 0.5:
            yellows.append(f"⚠ Лише {locked*100:.0f}% LP заблоковано — ризик rug-pull")
            score += 12
        else:
            greens.append(f"✓ {locked*100:.0f}% ліквідності заблоковано")

    # --- концентрація холдерів ----------------------------------------
    holders_list = g.get("holders") or []
    top1 = _f(holders_list[0].get("percent")) * 100 if holders_list else 0.0
    if top1:
        facts.append(("Топ-1 холдер", f"{top1:.1f}%"))
        if top1 >= 50:
            reds.append(f"✗ Один гаманець тримає {top1:.0f}% — висока маніпулятивність")
            score += 15
        elif top1 >= 20:
            yellows.append(f"⚠ Топ-холдер тримає {top1:.0f}%")
            score += 7

    if holders:
        facts.append(("Холдерів", f"{holders:,}".replace(",", " ")))
        if holders < 100:
            yellows.append(f"⚠ Мало холдерів ({holders}) — низька довіра/ліквідність")
            score += 8

    # --- whitelist довіри ----------------------------------------------
    if _truthy(g.get("trust_list")):
        greens.append("✓ У білому списку довірених токенів GoPlus")
        score = max(0.0, score - 10)

    score = min(round(score, 1), 100.0)
    if score < 20:
        category = "НИЗЬКИЙ РИЗИК"
    elif score < 45:
        category = "ПОМІРНИЙ РИЗИК"
    elif score < 70:
        category = "ВИСОКИЙ РИЗИК"
    else:
        category = "КРИТИЧНИЙ РИЗИК"

    return {
        "name": name,
        "symbol": symbol,
        "chain": chain.lower(),
        "address": address,
        "score": score,
        "category": category,
        "reds": reds,
        "yellows": yellows,
        "greens": greens,
        "facts": facts,
    }
