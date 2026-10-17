"""Fundamentaldaten aller Werte (wöchentlich) und Branchen-Mediane für den Vergleich."""
import statistics
import time
from datetime import datetime, timedelta, timezone

from . import config, store
from .indicators import safe

FIELDS = {
    "pe": "trailingPE", "fpe": "forwardPE", "rev_growth": "revenueGrowth",
    "eps_growth": "earningsGrowth", "margin": "profitMargins", "de": "debtToEquity",
    "mcap": "marketCap", "target": "targetMeanPrice", "rec": "recommendationKey",
}


def extract(info: dict) -> dict:
    out = {k: (info.get(v) if k == "rec" else safe(info.get(v))) for k, v in FIELDS.items()}
    out["sector"] = info.get("sector") or ""
    out["industry"] = info.get("industry") or ""
    out["currency"] = info.get("currency") or ""
    out["name"] = info.get("longName") or info.get("shortName") or ""
    out["summary"] = (info.get("longBusinessSummary") or "")[:400]
    return out


def sector_medians(items: dict) -> dict:
    groups: dict[str, dict[str, list]] = {}
    for f in items.values():
        sec = f.get("sector")
        if not sec:
            continue
        g = groups.setdefault(sec, {"pe": [], "rev_growth": [], "margin": [], "de": []})
        if f.get("pe") and 0 < f["pe"] < 300:
            g["pe"].append(f["pe"])
        for k in ("rev_growth", "margin", "de"):
            if f.get(k) is not None:
                g[k].append(f[k])
    return {sec: {k: (round(statistics.median(v), 4) if len(v) >= 3 else None) for k, v in g.items()}
            | {"n": max(len(v) for v in g.values())}
            for sec, g in groups.items()}


def build(universe: dict, provider, pause: float = 0.3) -> dict:
    old = store.load("state", "fundamentals", {}) or {}
    items = dict(old.get("items", {}))
    ok = 0
    for t in universe["tickers"]:
        info = provider.info(t["symbol"])
        if info:
            items[t["symbol"]] = extract(info)
            ok += 1
        time.sleep(pause)
    data = {"updated": datetime.now(timezone.utc).isoformat(), "items": items,
            "sector_medians": sector_medians(items), "ok": ok}
    store.save("state", "fundamentals", data)
    return data


def load() -> dict:
    return store.load("state", "fundamentals", {"items": {}, "sector_medians": {}}) or \
        {"items": {}, "sector_medians": {}}


def is_stale() -> bool:
    f = store.load("state", "fundamentals")
    if not f or not f.get("updated"):
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(f["updated"])
    return age > timedelta(days=config.FUNDAMENTALS_MAX_AGE_DAYS)
