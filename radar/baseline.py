"""Tägliche Basisdaten (vor Börsenstart): Vortagesschluss, Durchschnittsvolumen,
Trendlinien, RSI, 52-Wochen-Hoch. Daraus entsteht auch die Frühwarn-Watchlist."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import config, store
from .indicators import rsi, safe, sma
from .market_hours import MARKETS, is_closed_for_day, local_today


def _complete_days(df: pd.DataFrame, market: str, now) -> pd.DataFrame:
    """Heutige, noch laufende Tageskerze entfernen."""
    if df.empty:
        return df
    last = pd.Timestamp(df.index[-1]).date()
    if last >= local_today(market, now) and not is_closed_for_day(market, now):
        return df.iloc[:-1]
    return df


def compute_metrics(df: pd.DataFrame, market: str, now=None) -> dict | None:
    df = _complete_days(df.dropna(subset=["Close"]), market, now)
    if len(df) < 30:
        return None
    c, v, h = df["Close"].astype(float), df["Volume"].astype(float).fillna(0), df["High"].astype(float)
    n = config.VOLUME_AVG_DAYS
    avg_vol = float(v.iloc[-n:].mean())
    prev_avg_vol = float(v.iloc[-n - 1:-1].mean()) if len(v) > n else avg_vol
    range_hi = float(h.iloc[-21:-1].max())
    range_lo = float(df["Low"].astype(float).iloc[-21:-1].min())
    prior_high52 = float(h.iloc[-253:-1].max())
    return {
        "prev_close": safe(c.iloc[-1]),
        "prev_date": str(pd.Timestamp(df.index[-1]).date()),
        "avg_vol20": safe(avg_vol, 0),
        "turnover20": safe((c.iloc[-n:] * v.iloc[-n:]).mean(), 0),
        "sma50": safe(sma(c, 50)),
        "sma200": safe(sma(c, 200)),
        "high52": safe(h.iloc[-252:].max()),
        "low52": safe(df["Low"].astype(float).iloc[-252:].min()),
        "rsi14": safe(rsi(c), 1),
        "closes": [safe(x) for x in c.iloc[-60:]],
        "perf20": safe(c.iloc[-1] / c.iloc[-21] - 1 if len(c) > 21 else None),
        # Signale des letzten vollständigen Handelstags (für die Watchlist)
        "last_change": safe(c.iloc[-1] / c.iloc[-2] - 1),
        "last_vol_ratio": safe(v.iloc[-1] / prev_avg_vol if prev_avg_vol else None, 2),
        "range20_high": safe(range_hi),
        "range20_width": safe((range_hi - range_lo) / range_lo if range_lo else None),
        "new_high52": bool(c.iloc[-1] > prior_high52),
    }


def build(universe: dict, provider, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    tickers = universe["tickers"]
    symbols = [t["symbol"] for t in tickers]
    market_of = {t["symbol"]: t["market"] for t in tickers}
    hist = provider.history(symbols + [m["index"] for m in MARKETS.values()], period="1y")

    items, failed = {}, []
    for sym in symbols:
        df = hist.get(sym)
        m = compute_metrics(df, market_of[sym], now) if df is not None else None
        if m:
            items[sym] = m
        else:
            failed.append(sym)
    index_perf = {}
    for mk, meta in MARKETS.items():
        df = hist.get(meta["index"])
        im = compute_metrics(df, mk, now) if df is not None else None
        index_perf[mk] = im["perf20"] if im else None

    base = {"built": now.isoformat(), "items": items, "index_perf20": index_perf,
            "failed": failed[:50], "failed_count": len(failed)}
    store.save("state", "baseline", base)
    return base


def ensure(universe: dict, provider, now=None) -> tuple[dict, bool]:
    now = now or datetime.now(timezone.utc)
    base = store.load("state", "baseline")
    if base and base.get("items"):
        age = now - datetime.fromisoformat(base["built"])
        if age < timedelta(hours=config.BASELINE_MAX_AGE_HOURS):
            return base, False
    return build(universe, provider, now), True


# --------------------------------------------------------------------------
# Frühwarn-Watchlist
# --------------------------------------------------------------------------
def watchlist(universe: dict, base: dict, provider, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    meta = {t["symbol"]: t for t in universe["tickers"]}
    candidates = []
    for sym, m in base["items"].items():
        t = meta.get(sym)
        if not t or (m["prev_close"] or 0) < config.MIN_PRICE:
            continue
        if (m["turnover20"] or 0) < config.MIN_AVG_TURNOVER:
            continue
        signals, points = [], 0
        chg = (m["last_change"] or 0) * 100
        if (m["last_vol_ratio"] or 0) >= config.WATCH_VOLUME_SPIKE and abs(chg) < config.WATCH_QUIET_MOVE_PCT:
            signals.append(f"Ungewöhnliches Volumen ({m['last_vol_ratio']:.1f}×) ohne große Kursbewegung")
            points += 3
        if (m["range20_width"] is not None and m["range20_width"] < config.WATCH_RANGE_WIDTH
                and m["prev_close"] > m["range20_high"]):
            signals.append("Ausbruch aus einer engen Seitwärtsphase")
            points += 3
        if m["new_high52"]:
            signals.append("Schlusskurs auf neuem 52-Wochen-Hoch")
            points += 2
        idx = base["index_perf20"].get(t["market"])
        if m["perf20"] is not None and idx is not None:
            rel = (m["perf20"] - idx) * 100
            if rel >= config.WATCH_REL_STRENGTH:
                signals.append(f"Starkes relatives Momentum (+{rel:.0f} %-Punkte ggü. Index in 20 Tagen)")
                points += 2
        if (m["rsi14"] or 0) > 80:
            points -= 1   # bereits überkauft
        if signals:
            candidates.append({"symbol": sym, "name": t["name"], "market": t["market"],
                               "price": m["prev_close"], "last_change_pct": safe(chg, 2),
                               "rsi14": m["rsi14"], "signals": signals, "points": points})

    candidates.sort(key=lambda x: (-x["points"], -(x["last_change_pct"] or 0)))
    top = candidates[: config.WATCHLIST_MAX * 2]
    # Termin der Quartalszahlen nur für die engere Auswahl abfragen (spart Abrufe)
    for c in top:
        d = provider.next_earnings(c["symbol"])
        if d:
            days = (d - now.date()).days
            if 0 <= days <= config.WATCH_EARNINGS_DAYS:
                c["signals"].append(f"Quartalszahlen in {days} Tag(en) ({d.strftime('%d.%m.')})")
                c["points"] += 2
                c["earnings"] = str(d)
    top.sort(key=lambda x: (-x["points"], -(x["last_change_pct"] or 0)))
    result = {"updated": now.isoformat(), "items": top[: config.WATCHLIST_MAX],
              "hinweis": "Frühwarn-Signale sind Hinweise auf erhöhte Bewegungswahrscheinlichkeit, "
                         "keine Prognose und keine Kaufempfehlung."}
    store.save("public", "watchlist", result)
    return result
