"""Kompletter Durchlauf mit synthetischen Daten – ohne Internet.

Aufruf:  python tests/test_offline.py
Erzeugt außerdem Beispieldaten für die Web-App unter docs/sample/.
"""
import json
import zlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="radar-test-"))
os.environ["RADAR_STORE"] = str(TMP)
os.environ["NTFY_TOPIC"] = ""                      # Push nur simulieren
os.environ["GITHUB_REPOSITORY"] = "beispiel/aktien-radar"
sys.path.insert(0, str(ROOT))

from radar import baseline, config, jobs, notify, store  # noqa: E402

# Dienstag, 13.10.2026, 13:00 UTC = 15:00 Berlin (Xetra offen), US noch zu
T1 = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)
# 15:30 UTC = 17:30 Berlin (Xetra zu) / 11:30 New York (US offen)
T2 = datetime(2026, 10, 13, 15, 30, tzinfo=timezone.utc)

SPECIAL = {  # Symbol: (Tagesänderung, Volumenfaktor, Nachrichtentitel)
    "HOT1.DE": (0.14, 4.0, "Musterwerk AG hebt Prognose nach starkem Quartal an"),
    "HOT2": (0.22, 6.0, "Example Corp beats Q3 earnings estimates, raises guidance"),
    "TAKE4": (0.31, 9.0, "Bigco agrees to acquire Target Inc in $5bn takeover"),
    "MEME5": (0.45, 12.0, "Retail traders pile into stock"),
    "LOWV.DE": (0.12, 1.2, "Keine Nachricht"),       # zu wenig Volumen -> kein Alarm
    "SMALL.DE": (0.15, 5.0, ""),                     # unter 1 € -> kein Alarm
}


def make_universe():
    tickers = []
    for i in range(300):
        tickers.append({"symbol": f"US{i:03d}", "name": f"US Company {i}", "market": "US",
                        "sector": "Technology" if i % 2 else "Industrials", "indices": ["S&P 500"]})
    for i in range(160):
        tickers.append({"symbol": f"DE{i:03d}.DE", "name": f"Deutsche Firma {i}", "market": "DE",
                        "sector": "Industrials", "indices": ["MDAX"]})
    for sym in SPECIAL:
        mk = "DE" if sym.endswith(".DE") else "US"
        tickers.append({"symbol": sym, "name": sym.replace(".DE", "") + " Testwert", "market": mk,
                        "sector": "Technology", "indices": ["DAX" if mk == "DE" else "Nasdaq 100"]})
    # Watchlist-Kandidat: enge Seitwärtsphase + Ausbruch gestern
    tickers.append({"symbol": "BRK1.DE", "name": "Ausbruch AG", "market": "DE", "sector": "Industrials",
                    "indices": ["SDAX"]})
    store.save("state", "universe", {"updated": datetime.now(timezone.utc).isoformat(), "tickers": tickers,
                                     "report": {"Test": len(tickers)}})


class FakeProvider:
    def __init__(self, now):
        self.now = now

    def _series(self, sym):
        rng = np.random.default_rng(zlib.crc32(sym.encode()))
        days = pd.bdate_range(end=self.now.date(), periods=260)
        start = 0.5 if sym == "SMALL.DE" else rng.uniform(20, 300)
        drift = 0.0006
        rets = rng.normal(drift, 0.015, len(days))
        if sym == "BRK1.DE":
            rets[-25:-1] = rng.normal(0, 0.002, 24)   # Seitwärts
            rets[-2] = 0.045                           # Ausbruch am Vortag
        close = start * np.exp(np.cumsum(rets))
        vol = rng.uniform(2e5, 2e6, len(days))
        if sym == "BRK1.DE":
            vol[-2] *= 3
        spec = SPECIAL.get(sym)
        mk = "DE" if sym.endswith(".DE") else "US"
        from radar.market_hours import session_fraction
        frac = max(session_fraction(mk, self.now), 0.15)
        if spec:
            close[-1] = close[-2] * (1 + spec[0])
            vol[-1] = vol[-21:-1].mean() * spec[1] * frac
        else:
            vol[-1] = vol[-21:-1].mean() * frac
        df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                           "Close": close, "Adj Close": close, "Volume": vol}, index=days)
        return df

    def history(self, symbols, period="1y"):
        out = {}
        for s in symbols:
            df = self._series(s)
            out[s] = df.iloc[-5:] if period == "5d" else df
        return out

    def info(self, sym):
        if sym == "MEME5":
            return {"longName": "Meme Inc", "sector": "Technology", "trailingPE": -3,
                    "revenueGrowth": -0.2, "profitMargins": -0.4, "debtToEquity": 320}
        return {"longName": sym + " Holding", "sector": "Technology", "industry": "Software",
                "trailingPE": 18.5, "forwardPE": 16.0, "revenueGrowth": 0.21, "earningsGrowth": 0.3,
                "profitMargins": 0.19, "debtToEquity": 45.0, "marketCap": 12e9, "currency": "USD",
                "targetMeanPrice": 150.0, "recommendationKey": "buy",
                "longBusinessSummary": "Testunternehmen für den Offline-Test."}

    def news(self, sym):
        title = (SPECIAL.get(sym) or (0, 0, ""))[2]
        if not title:
            return []
        return [{"title": title, "url": "https://example.com/news", "publisher": "Testwire",
                 "time": (self.now - timedelta(hours=2)).isoformat()}]

    def next_earnings(self, sym):
        return (self.now + timedelta(days=4)).date() if sym in ("BRK1.DE", "HOT2") else None

    def search_symbol(self, name, suffix=".DE"):
        return None


def main():
    make_universe()
    # Fundamentaldaten-Cache mit Branchen-Medianen
    store.save("state", "fundamentals", {"updated": T1.isoformat(), "items": {},
                                         "sector_medians": {"Technology": {"pe": 28.0, "rev_growth": 0.08,
                                                                           "margin": 0.12, "de": 60, "n": 120}}})
    sent = []
    notify.send = lambda title, msg, **kw: sent.append((title, msg, kw)) or True

    # Tageslauf am Morgen
    morning = T1.replace(hour=5, minute=20)
    jobs.daily(FakeProvider(morning), now=morning)
    wl = store.load("public", "watchlist")
    assert any(w["symbol"] == "BRK1.DE" for w in wl["items"]), "Ausbruchskandidat fehlt in Watchlist"
    print(f"Watchlist: {len(wl['items'])} Einträge, z. B. {wl['items'][0]['symbol']}: {wl['items'][0]['signals']}")

    # Scan 1: nur Xetra offen
    r1 = jobs.scan(FakeProvider(T1), now=T1)
    alerts = store.load("public", "alerts")
    syms = {a["symbol"] for a in alerts["items"]}
    assert syms == {"HOT1.DE"}, f"Erwartet nur HOT1.DE, bekommen {syms}"

    # Scan 2: Xetra zu, US offen
    r2 = jobs.scan(FakeProvider(T2), now=T2)
    alerts = store.load("public", "alerts")
    syms = {a["symbol"] for a in alerts["items"]}
    assert {"HOT2", "TAKE4", "MEME5"} <= syms and "LOWV.DE" not in syms and "SMALL.DE" not in syms, syms

    # Scan 3: gleiche Lage -> kein doppelter Push
    before = len(sent)
    jobs.scan(FakeProvider(T2 + timedelta(minutes=5)), now=T2 + timedelta(minutes=5))
    assert len(sent) == before, "Doppelter Alarm!"

    det = {a["symbol"]: store.load("public", f"a/{a['id']}") for a in alerts["items"]}
    for sym, a in det.items():
        print(f"\n{a['ampel']['emoji']} {sym} {a['change_pct']:+.1f} % | Score {a['score']} ({a['ampel']['label']}) "
              f"| K/M/L {[h['score'] for h in a['horizonte'].values()]}\n   Grund: {a['grund']['label']}"
              f"\n   {a['begruendung']}")
    assert det["HOT2"]["ampel"]["farbe"] == "gruen", det["HOT2"]["score"]
    assert det["MEME5"]["ampel"]["farbe"] == "rot", det["MEME5"]["score"]
    assert det["TAKE4"]["score"] <= 55
    assert det["TAKE4"]["grund"]["key"] == "takeover"

    print("\nPush-Nachrichten:")
    for t, m, kw in sent:
        print(f"  [{kw.get('priority')}] {t} | {m.splitlines()[0]} | {kw.get('click')}")
    assert all(kw.get("priority") == 5 for t, m, kw in sent if t.startswith("🚀"))

    probs = jobs.selfcheck(now=T2 + timedelta(minutes=6))
    assert not probs, probs

    # Fehlerpfad: Datenquelle liefert nichts
    class Broken(FakeProvider):
        def history(self, symbols, period="1y"):
            return {} if period == "5d" else super().history(symbols, period)
    try:
        jobs.run_guarded("scan", jobs.scan, Broken(T2), now=T2)
        raise AssertionError("Fehler wurde nicht erkannt")
    except RuntimeError:
        pass
    assert store.load("public", "status")["errors"], "Fehler nicht protokolliert"

    # Beispieldaten für die Web-App sichern
    sample = ROOT / "docs" / "sample"
    if sample.exists():
        shutil.rmtree(sample)
    shutil.copytree(config.PUBLIC, sample)
    st = json.loads((sample / "status.json").read_text())
    st["errors"] = []
    st["ok"] = True
    (sample / "status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1))
    print(f"\nAlle Tests bestanden. Beispieldaten: {sample}")


if __name__ == "__main__":
    main()
