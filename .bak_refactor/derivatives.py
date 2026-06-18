"""
БЛОК 4 (частина) — дані деривативів із публічного API OKX (БЕЗ ключів).

- Funding rate (поточний + наступний прогноз)
- Open Interest (відкритий інтерес, USD)
- Long/Short account ratio (співвідношення лонгів до шортів)
- Інтерпретація простою мовою (сентимент ринку ф'ючерсів)

Працює для монет, у яких на OKX є безстроковий контракт {SYMBOL}-USDT-SWAP.
"""

import requests
import cache

OKX = "https://www.okx.com/api/v5"
HEADERS = {"User-Agent": "CryptoRiskBot/4.0"}


class DerivUnavailable(Exception):
    """Немає деривативів для монети на OKX."""


def _get(path: str, params: dict) -> list:
    r = requests.get(OKX + path, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("code") not in ("0", 0):
        return []
    return j.get("data") or []


def derivatives_overview(symbol: str) -> dict:
    """Повертає зведення деривативів для монети."""
    sym = symbol.upper()
    inst = f"{sym}-USDT-SWAP"

    def fetch():
        fr = _get("/public/funding-rate", {"instId": inst})
        if not fr:
            raise DerivUnavailable(
                f"Немає безстрокового контракту {inst} на OKX — "
                f"деривативи недоступні для {sym}."
            )
        f = fr[0]
        oi = _get("/public/open-interest", {"instId": inst})
        ls = _get("/rubik/stat/contracts/long-short-account-ratio",
                  {"ccy": sym, "period": "5m"})

        funding = float(f.get("fundingRate") or 0) * 100
        next_funding = float(f.get("nextFundingRate") or 0) * 100
        oi_usd = float(oi[0].get("oiUsd")) if oi else 0.0
        ls_ratio = float(ls[0][1]) if ls else 0.0  # дані від нових до старих

        return {
            "symbol": sym,
            "funding_pct": round(funding, 4),
            "next_funding_pct": round(next_funding, 4),
            "oi_usd": oi_usd,
            "long_short_ratio": round(ls_ratio, 2),
        }

    data = cache.cached(f"deriv:{inst}", fetch, ttl=60)

    # --- інтерпретація -----------------------------------------------------
    notes = []
    f = data["funding_pct"]
    if f > 0.05:
        notes.append("Funding сильно додатний — лонги переплачують, перегрів зверху")
    elif f > 0:
        notes.append("Funding додатний — перевага лонгів")
    elif f < -0.05:
        notes.append("Funding сильно від'ємний — шорти переплачують, можливий сквіз")
    elif f < 0:
        notes.append("Funding від'ємний — перевага шортів")
    else:
        notes.append("Funding нейтральний")

    ls = data["long_short_ratio"]
    if ls:
        if ls > 1.5:
            notes.append(f"L/S {ls} — натовп у лонгах (контр-сигнал на падіння)")
        elif ls < 0.7:
            notes.append(f"L/S {ls} — натовп у шортах (контр-сигнал на ріст)")
        else:
            notes.append(f"L/S {ls} — збалансовано")

    data["notes"] = notes
    return data
