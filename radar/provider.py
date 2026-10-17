"""Datenquelle (Yahoo Finance über yfinance).

Alles, was ins Internet geht, ist hier gekapselt. Die Tests ersetzen diese
Klasse durch eine Attrappe mit synthetischen Daten.
"""
import time
from datetime import datetime, timezone

import pandas as pd


class YahooProvider:
    def __init__(self, chunk: int = 100, pause: float = 1.0):
        import yfinance as yf  # erst hier importieren, damit Tests ohne Netz laufen
        self.yf = yf
        self.chunk = chunk
        self.pause = pause

    # ---- Kurse -----------------------------------------------------------
    def history(self, symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(symbols), self.chunk):
            part = symbols[i:i + self.chunk]
            df = None
            for attempt in range(3):
                try:
                    df = self.yf.download(part, period=period, interval="1d", group_by="ticker",
                                          auto_adjust=False, threads=True, progress=False)
                    break
                except Exception as exc:  # Netzwerk-/Rate-Limit-Fehler
                    print(f"[provider] Download-Fehler (Versuch {attempt + 1}): {exc}")
                    time.sleep(5 * (attempt + 1))
            if df is None or df.empty:
                continue
            out.update(_split_frame(df, part))
            time.sleep(self.pause)
        return out

    # ---- Unternehmensdaten ----------------------------------------------
    def info(self, symbol: str) -> dict:
        try:
            return self.yf.Ticker(symbol).info or {}
        except Exception as exc:
            print(f"[provider] info({symbol}) fehlgeschlagen: {exc}")
            return {}

    def news(self, symbol: str) -> list[dict]:
        try:
            raw = self.yf.Ticker(symbol).news or []
        except Exception as exc:
            print(f"[provider] news({symbol}) fehlgeschlagen: {exc}")
            return []
        return [n for n in (normalize_news(item) for item in raw) if n]

    def next_earnings(self, symbol: str):
        """Datum der nächsten Quartalszahlen oder None."""
        try:
            cal = self.yf.Ticker(symbol).calendar
        except Exception:
            return None
        dates = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date")
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            dates = list(cal.loc["Earnings Date"].values)
        if not dates:
            return None
        if not isinstance(dates, (list, tuple)):
            dates = [dates]
        try:
            return pd.Timestamp(dates[0]).date()
        except Exception:
            return None

    def search_symbol(self, name: str, suffix: str = ".DE") -> str | None:
        """Firmennamen in ein Börsenkürzel übersetzen (für Indexlisten ohne Kürzel)."""
        try:
            quotes = self.yf.Search(name, max_results=10, news_count=0).quotes
        except Exception:
            return None
        for q in quotes:
            sym = q.get("symbol", "")
            if sym.endswith(suffix) and q.get("quoteType") == "EQUITY":
                return sym
        return None


def _split_frame(df: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    if isinstance(df.columns, pd.MultiIndex):
        level0 = set(df.columns.get_level_values(0))
        for sym in symbols:
            if sym in level0:
                sub = df[sym].dropna(how="all")
                if not sub.empty and "Close" in sub:
                    out[sym] = sub
    elif len(symbols) == 1 and "Close" in df:
        out[symbols[0]] = df.dropna(how="all")
    return out


def normalize_news(item: dict) -> dict | None:
    """Beide Formate der Yahoo-News-API auf {title, url, publisher, time} bringen."""
    if not isinstance(item, dict):
        return None
    c = item.get("content") if isinstance(item.get("content"), dict) else None
    if c:
        title = c.get("title")
        url = ((c.get("clickThroughUrl") or {}).get("url")
               or (c.get("canonicalUrl") or {}).get("url"))
        publisher = (c.get("provider") or {}).get("displayName", "")
        ts = c.get("pubDate") or c.get("displayTime")
        try:
            when = pd.Timestamp(ts).tz_convert("UTC").to_pydatetime() if ts else None
        except Exception:
            when = None
    else:
        title = item.get("title")
        url = item.get("link")
        publisher = item.get("publisher", "")
        t = item.get("providerPublishTime")
        when = datetime.fromtimestamp(t, tz=timezone.utc) if t else None
    if not title:
        return None
    return {"title": title, "url": url, "publisher": publisher,
            "time": when.isoformat() if when else None}
