"""Aktienuniversum: DAX, MDAX, SDAX (TecDAX-Werte sind darin enthalten),
S&P 500 und Nasdaq 100. Quelle: Wikipedia-Indexlisten, wöchentlich aktualisiert.
Fällt eine Quelle aus, bleibt die letzte bekannte Liste dieses Index erhalten."""
from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import requests

from . import config, store

UA = {"User-Agent": "Mozilla/5.0 (AktienRadar; +https://github.com)"}

SOURCES = {
    "S&P 500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "US"),
    "Nasdaq 100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "US"),
    "DAX": ("https://en.wikipedia.org/wiki/DAX", "DE"),
    "MDAX": ("https://en.wikipedia.org/wiki/MDAX", "DE"),
    "SDAX": ("https://en.wikipedia.org/wiki/SDAX", "DE"),
}

# Notfall-Liste, falls beim allerersten Lauf keine Quelle erreichbar ist.
SEED_DAX = ["ADS.DE", "AIR.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BEI.DE", "BMW.DE", "BNR.DE",
            "CBK.DE", "CON.DE", "1COV.DE", "DTG.DE", "DBK.DE", "DB1.DE", "DHL.DE", "DTE.DE",
            "EOAN.DE", "FRE.DE", "HNR1.DE", "HEI.DE", "HEN3.DE", "IFX.DE", "MBG.DE", "MRK.DE",
            "MTX.DE", "MUV2.DE", "P911.DE", "PAH3.DE", "QIA.DE", "RHM.DE", "RWE.DE", "SAP.DE",
            "SRT3.DE", "SIE.DE", "ENR.DE", "SHL.DE", "SY1.DE", "VOW3.DE", "VNA.DE", "ZAL.DE"]


def _tables(url: str) -> list[pd.DataFrame]:
    html = requests.get(url, headers=UA, timeout=30).text
    tables = pd.read_html(StringIO(html))
    for t in tables:
        t.columns = [" ".join(str(c) for c in col) if isinstance(col, tuple) else str(col)
                     for col in t.columns]
    return tables


def _col(df: pd.DataFrame, *names: str) -> str | None:
    for n in names:
        for c in df.columns:
            if c.strip().lower() == n.lower():
                return c
    return None


def _parse(index: str, market: str, tables: list[pd.DataFrame], provider, name_cache: dict) -> list[dict]:
    best: list[dict] = []
    for t in tables:
        sym_c = _col(t, "Symbol", "Ticker", "Ticker symbol")
        name_c = _col(t, "Security", "Company", "Name")
        sector_c = _col(t, "GICS Sector", "Prime Standard Sector", "Industry")
        if not name_c or (not sym_c and index != "SDAX"):
            continue
        rows = []
        for _, r in t.iterrows():
            name = str(r[name_c]).strip()
            if not name or name.lower() == "nan":
                continue
            sym = str(r[sym_c]).strip() if sym_c else ""
            if market == "US":
                sym = sym.replace(".", "-")
            elif sym and sym.lower() != "nan":
                sym = sym.split(".")[0] + ".DE"   # Xetra-Notierung verwenden
            else:
                sym = name_cache.get(name) or (provider.search_symbol(name) if provider else None)
                if not sym:
                    continue
                name_cache[name] = sym
            sector = str(r[sector_c]).strip() if sector_c and str(r[sector_c]) != "nan" else ""
            rows.append({"symbol": sym, "name": name, "market": market, "sector": sector})
        if len(rows) > len(best):
            best = rows
    return best


def build(provider=None, fetch_tables=_tables) -> dict:
    old = store.load("state", "universe", {}) or {}
    name_cache = old.get("name_cache", {})
    by_index_old = old.get("by_index", {})
    by_index: dict[str, list[dict]] = {}
    report = {}
    for index, (url, market) in SOURCES.items():
        try:
            rows = _parse(index, market, fetch_tables(url), provider, name_cache)
            if len(rows) < 15:
                raise ValueError(f"nur {len(rows)} Werte gefunden")
            by_index[index] = rows
            report[index] = len(rows)
        except Exception as exc:
            by_index[index] = by_index_old.get(index, [])
            report[index] = f"Fehler ({exc}); alte Liste: {len(by_index[index])}"
    if not by_index.get("DAX"):
        by_index["DAX"] = [{"symbol": s, "name": s, "market": "DE", "sector": ""} for s in SEED_DAX]

    merged: dict[str, dict] = {}
    for index, rows in by_index.items():
        for r in rows:
            e = merged.setdefault(r["symbol"], {**r, "indices": []})
            e["indices"].append(index)
            if not e.get("sector") and r.get("sector"):
                e["sector"] = r["sector"]
    for line in _extra_lines():
        sym, name, market = (line.split(";") + ["", ""])[:3]
        merged.setdefault(sym, {"symbol": sym, "name": name or sym, "market": market or "US",
                                "sector": "", "indices": ["Eigene Liste"]})

    uni = {"updated": datetime.now(timezone.utc).isoformat(), "report": report,
           "by_index": by_index, "name_cache": name_cache,
           "tickers": sorted(merged.values(), key=lambda x: x["symbol"])}
    store.save("state", "universe", uni)
    return uni


def _extra_lines() -> list[str]:
    p = config.ROOT / "config" / "extra_tickers.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def ensure(provider=None, force: bool = False) -> dict:
    uni = store.load("state", "universe")
    if uni and not force:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(uni["updated"])
        if age < timedelta(days=config.UNIVERSE_MAX_AGE_DAYS) and uni.get("tickers"):
            return uni
    return build(provider)
