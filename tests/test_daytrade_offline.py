"""Daytrading- und Kongress-Module mit echten, gespeicherten Daten – ohne Internet.

Aufruf:  python tests/test_daytrade_offline.py
Daten: Tesla & 233 weitere US-Aktien am Montag, 19.10.2026 (5-Min.-Kerzen bis 10:58 New York),
60 Tage Tesla-Kerzen für die Time Machine, Tagescharts von 19 Aktien und der Index 2026
des House Clerk mit echten PTR-Texten. Erzeugt außerdem Beispieldaten für die Web-App.
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="radar-dt-test-"))
os.environ["RADAR_STORE"] = str(TMP)
os.environ["NTFY_TOPIC"] = ""
os.environ["GITHUB_REPOSITORY"] = "beispiel/aktien-radar"
os.environ.pop("RADAR_PUBLISH", None)
sys.path.insert(0, str(ROOT))

from radar import config, congress, daytrade, jobs, notify, store  # noqa: E402
from radar.vendor.daytrader import ptr as P, scan as S  # noqa: E402

FIX = ROOT / "tests" / "daytrader" / "fixtures"
NY = daytrade.NEW_YORK


def ny(text: str) -> datetime:
    """'2026-10-19 10:15:45' New York -> aware UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=NY).astimezone(timezone.utc)


class FakeNet:
    """Liefert die gespeicherten Yahoo-/Nasdaq-Antworten statt des Internets."""

    def __init__(self):
        self.daily = json.loads((FIX / "trader-scanner" / "daily-spark-2026-10-19.json").read_text())
        self.wall = json.load(gzip.open(FIX / "trader-scanner" / "wall5m-2026-10-19.json.gz", "rt"))
        self.tsla_1d = (FIX / "trader-entry" / "TSLA-2026-10-19-5m.json").read_text()
        self.tsla_60d = gzip.open(FIX / "trader-timemachine" / "TSLA-60d5m.json.gz", "rt").read()
        self.calls = {"spark": 0, "chart": 0, "60d": 0}
        self.symbols = [r["symbol"] for r in self.daily["spark"]["result"]]

    def new_cycle(self):
        pass

    def nasdaq_files(self):
        head = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"
        rows = [f"{s}|{s} Corp. - Common Stock|Q|N|N|100|N|N" for s in self.symbols]
        rows += ["ZZTEST|Test Issue Inc. - Common Stock|Q|Y|N|100|N|N", "QQQ|Invesco QQQ Trust|G|N|N|100|Y|N"]
        other = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol"
        return {"nasdaqlisted.txt": "\n".join([head] + rows + ["File Creation Time: 1019202608:00|||||||"]),
                "otherlisted.txt": other + "\nFile Creation Time: 1019202608:00|||||||"}

    def spark(self, symbols, rng, interval):
        self.calls["spark"] += 1
        if interval == "1d":
            data = S.parse_spark(self.daily)
        else:  # 5-Min.-Kerzen des Tages aus den gespeicherten v8-Charts
            data = {s: S.parse_chart(self.wall[s], s) for s in symbols if s in self.wall}
        return {s: data[s] for s in symbols if s in data}, {s: "keine Daten" for s in symbols if s not in data}

    def chart_text(self, sym, rng):
        if rng == "60d":
            self.calls["60d"] += 1
            if sym == "TSLA":
                return self.tsla_60d
            raise S.ScanError(f"no data for {sym}: offline")
        self.calls["chart"] += 1
        if sym == "TSLA":
            return self.tsla_1d
        if sym in self.wall:
            return json.dumps(self.wall[sym])
        raise S.ScanError(f"no data for {sym}")


class FakeCongressNet:
    TEXTS = {"20035590": "ptr-20035590.txt", "20035562": "ptr-20035562-excerpt.txt",
             "20035143": "ptr-20035143.txt", "20033725": "ptr-20033725-excerpt.txt"}

    def index(self, year):
        if year != 2026:
            raise P.PtrError("kein Index")
        return P.load_index(2026, str(FIX / "trader-pelosi" / "2026FD.zip"))

    def read_ptr(self, doc_id, year, filed, folder):
        name = self.TEXTS.get(doc_id)
        if not name:
            return None  # z. B. eingescannte Papiermeldung
        return P.parse_ptr_text((FIX / "trader-pelosi" / name).read_text(), filed=filed)


def test_daytrade(sent):
    daytrade.MIN_UNIVERSE = 10
    config.DT_ORB_MIN_PREV_VOLUME = 0          # Fixture-Volumen ist ein Zwischenstand
    daytrade._extra_watch = lambda: ["TSLA"]   # Tesla wie im Beispiel des Original-Skills
    net = FakeNet()

    # 1) Vorbörse 8:30 New York: Setups suchen
    r = daytrade.cycle(net, ny("2026-10-19 08:30"))
    assert r["phase"] == "pre-open", r
    setups = store.load("public", "setups")
    assert setups["universe"] == 19 and setups["scanned"] > 0, setups
    day = store.load("state", "dt_day")
    assert day["watch"][0]["symbol"] == "TSLA" and len(day["orb_symbols"]) >= 15, day["watch"][:3]
    print(f"Setups: {setups['hits_total']} Treffer {setups['per_setup']}, beobachtet: {setups['watch']}")

    # 2) 10:12 – Tesla wartet noch (die 10:10-Kerze läuft noch)
    daytrade.cycle(net, ny("2026-10-19 10:12:00"))
    e = {x["symbol"]: x for x in store.load("public", "entries")["items"]}
    assert e["TSLA"]["status"] == "waiting", e["TSLA"]
    orb = store.load("public", "orb")
    print(f"ORB 10:11: {len(orb['hits'])} Treffer, {orb['counts']}")
    assert orb["counts"]["scanned"] >= 15

    # 3) 10:15:45 – Einstieg ausgelöst bei 364,18 $; Plan wie im Original: Stop 358,32, Ziel 370,04
    daytrade.cycle(net, ny("2026-10-19 10:15:45"))
    e = {x["symbol"]: x for x in store.load("public", "entries")["items"]}
    t = e["TSLA"]
    assert t["status"] == "triggered", t
    assert t["trigger"]["price"] == 364.18 and t["trigger"]["time_et"] == "10:15", t["trigger"]
    assert t["trigger"]["time_berlin"] == "16:15", t["trigger"]
    assert (t["plan"]["stop"], t["plan"]["target"]) == (358.32, 370.04), t["plan"]
    tm = t["tm"]
    assert not tm.get("error"), tm
    assert abs(tm["p_target"] + tm["p_stop"] + tm["p_neither"] - 1) < 1e-3 and tm["replays"] == 10000
    assert tm["history"]["sessions"] >= 50 and tm["history"]["triggered"] > 10, tm["history"]
    detail = store.load("public", f"tm/{tm['id']}")
    assert detail["mc"]["bands"] and "sample_paths" not in detail["mc"]
    print(f"TSLA-Einstieg {t['trigger']['time_et']} ET: Ziel zuerst {tm['p_target']:.1%}, Stop zuerst "
          f"{tm['p_stop']:.1%}, offen {tm['p_neither']:.1%} → {tm['verdict']} | Historie {tm['history']}")
    pushes = [s for s in sent if s[0].startswith("🎯")]
    triggered = [x for x in e.values() if x["status"] == "triggered"]
    assert len(pushes) == len(triggered) >= 1, (pushes, triggered)
    tsla = [p for p in pushes if "TSLA" in p[0]]
    assert len(tsla) == 1 and tsla[0][2]["priority"] == 4 and "#/tm/" in tsla[0][2]["click"], tsla
    assert tsla[0][1].startswith("TSLA Corp.:"), tsla[0][1]
    for p in pushes:
        print("Push:", p[0], "|", p[1].replace("\n", " | "))

    # 4) Kein doppelter Push im nächsten Takt
    daytrade.cycle(net, ny("2026-10-19 10:20:45"))
    daytrade.cycle(net, ny("2026-10-19 10:25:45"))
    titles = [s[0].split()[2] for s in sent if s[0].startswith("🎯")]
    assert len(titles) == len(set(titles)), f"Doppelter Einstiegs-Push: {titles}"
    orb = store.load("public", "orb")
    assert orb["hits"], "keine ORB-Treffer"
    assert all(h["time_et"] <= "10:25" for h in orb["hits"])
    with_tm = [h for h in orb["hits"] if h.get("tm") and not h["tm"].get("error")]
    print(f"ORB bis 10:25: {len(orb['hits'])} Treffer, z. B. "
          f"{[(h['symbol'], h['time_et'], h['price']) for h in orb['hits'][:5]]}; Time Machine für {len(with_tm)}")
    st = store.load("public", "status")
    assert st["ok"] and st["phase"] == "open" and st["entries_triggered"] >= 1, st

    # 5) Ergebnis der Integration = Ergebnis des Original-Werkzeugs (gleicher Plan, Seed, Daten)
    from radar.vendor.daytrader import timemachine as TM
    plan = daytrade.make_plan("TSLA", "2026-10-19", 364.18, "10:15 AM", 362.18, 354.47)
    ref = TM.time_machine(net.tsla_60d, plan, daytrade.naive(ny("2026-10-19 10:15:45")), 10000, 19, 2, None)
    print(f"Referenz (bis 16:00, wie im Original-README): Ziel {ref['mc']['p_target']:.1%}, "
          f"Stop {ref['mc']['p_stop']:.1%}, offen {ref['mc']['p_neither']:.1%}; Historie "
          f"{ref['history']['triggered']}× / {ref['history']['target']} Ziel / {ref['history']['stop']} Stop")
    assert (round(ref["mc"]["p_target"], 3), round(ref["mc"]["p_stop"], 3), round(ref["mc"]["p_neither"], 3)) \
        == (0.294, 0.255, 0.451), ref["mc"]
    assert (ref["history"]["triggered"], ref["history"]["target"], ref["history"]["stop"]) == (33, 13, 15)

    # 6) Nach dem Einstiegsfenster: wartende Setups verfallen, Status sauber
    daytrade.cycle(net, ny("2026-10-19 15:40:45"))
    items = store.load("public", "entries")["items"]
    assert all(i["status"] in ("triggered", "expired", "error", "no-data") for i in items), \
        {i["symbol"]: i["status"] for i in items}
    assert store.load("public", "status")["phase"] == "after-cutoff"

    # 7) Wochenende / Feiertag: nichts tun
    assert daytrade.cycle(net, ny("2026-11-26 10:30"))["phase"] == "closed"   # Thanksgiving


def test_session_loop():
    """Die Schleife taktet alle 5 Min. ab 9:50:45 New York und endet nach 15:30."""
    calls = []
    clock = {"t": ny("2026-10-21 08:31")}

    def fake_cycle(net, now):
        calls.append(daytrade.et_of(now))
        return {}

    orig = daytrade.cycle
    daytrade.cycle = fake_cycle
    try:
        res = daytrade.session(None, max_minutes=600, now_fn=lambda: clock["t"],
                               sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + timedelta(seconds=s)),
                               publish_fn=lambda label: True)
    finally:
        daytrade.cycle = orig
    times = [c.strftime("%H:%M:%S") for c in calls]
    assert times[0] == "08:31:00" and times[1] == "09:50:45" and times[2] == "09:55:45", times[:4]
    assert times[-1] >= "15:36:00" and res["reason"] == "Sitzung beendet", (times[-3:], res)
    assert all((b - a) == timedelta(minutes=5) for a, b in zip(calls[1:-1], calls[2:-1]))
    print(f"Schleife: {len(calls)} Takte von {times[1]} bis {times[-1]} New York – {res['reason']}")

    # Laufzeit-Grenze: übergibt an den nächsten Lauf
    clock["t"] = ny("2026-10-21 08:31")
    daytrade.cycle = fake_cycle
    try:
        res = daytrade.session(None, max_minutes=120, now_fn=lambda: clock["t"],
                               sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + timedelta(seconds=s)),
                               publish_fn=lambda label: True)
    finally:
        daytrade.cycle = orig
    assert "Laufzeit" in res["reason"], res

    # Fehler im Takt: protokolliert, nach 6 in Folge Abbruch
    def broken(net, now):
        raise RuntimeError("Yahoo antwortet nicht")
    clock["t"] = ny("2026-10-21 10:00:45")
    daytrade.cycle = broken
    try:
        daytrade.session(None, max_minutes=600, now_fn=lambda: clock["t"],
                         sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + timedelta(seconds=s)),
                         publish_fn=lambda label: True)
        raise AssertionError("Abbruch nach Fehlern fehlt")
    except RuntimeError:
        pass
    finally:
        daytrade.cycle = orig
    st = store.load("public", "status")
    assert len(st["errors"]) >= 6 and not st["ok"], st
    store.save("public", "status", dict(st, errors=[], ok=True))


def test_congress(sent):
    cstore = TMP / "congress"
    config.STORE = cstore
    config.STATE, config.PUBLIC = cstore / "state", cstore / "public"
    net = FakeCongressNet()
    # Erster Lauf (14.10.2026): Meldungen der letzten 30 Tage, ohne Push
    r = congress.run(net, now=datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc))
    assert r["first_run"] and r["new"] >= 5 and not r["pushed"], r
    pub = store.load("public", "congress")
    by_id = {f["doc_id"]: f for f in pub["filings"]}
    g = by_id["20035590"]
    assert g["readable"] and g["rows"] and g["rows"][0]["type_de"] in ("Kauf", "Verkauf", "Teilverkauf", "Tausch")
    assert not by_id["20035635"]["readable"] and by_id["20035635"]["url"].endswith(".pdf")
    print(f"Kongress: {len(pub['filings'])} Meldungen, Gottheimer z. B.: "
          f"{[(x['type_de'], x['ticker'], congress.amount_de(x)) for x in g['rows'][:3]]}")
    # Zweiter Lauf: zwei bisher unbekannte Meldungen (eine von Pelosi) -> Push mit Priorität 4
    st = store.load("state", "congress")
    st["seen"] = [d for d in st["seen"] if d not in ("20035143", "20035562")]
    store.save("state", "congress", st)
    before = len(sent)
    r = congress.run(net, now=datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc))
    assert r["new"] == 2 and r["pushed"], r
    title, msg, kw = sent[before]
    assert "Pelosi" in title and kw["priority"] == 4 and kw["click"].endswith("#/kongress"), (title, kw)
    print("Push:", title, "|", msg.replace("\n", " | "))
    # Dritter Lauf: nichts Neues -> kein Push
    before = len(sent)
    r = congress.run(net, now=datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc))
    assert r["new"] == 0 and len(sent) == before
    top = store.load("public", "congress")["top"]
    assert top and top[0]["ticker"], top
    assert congress.amount_de({"amount_low": 1000001, "amount_high": 5000000}) == "1 Mio. – 5 Mio. $"
    assert congress.amount_de({"amount_low": 15001, "amount_high": 50000}) == "15 Tsd. – 50 Tsd. $"


def test_selfcheck():
    def status(branch):
        if branch == "daytrade":
            return {"date": "2026-10-21", "last_cycle": ny("2026-10-21 11:00").isoformat(), "errors": []}
        return {"congress_last": ny("2026-10-21 08:00").isoformat()}
    probs = jobs._check_daytrading(ny("2026-10-21 11:03"), status)
    assert not probs, probs
    probs = jobs._check_daytrading(ny("2026-10-21 12:00"), status)
    assert any("letzter Takt" in p for p in probs), probs
    probs = jobs._check_daytrading(ny("2026-10-22 11:00"), status)
    assert any("heute noch kein Lauf" in p for p in probs), probs
    probs = jobs._check_daytrading(ny("2026-10-26 11:00"), status)
    assert any("Kongress" in p for p in probs), probs
    probs = jobs._check_daytrading(ny("2028-01-04 11:00"), lambda b: None)
    assert any("Feiertagskalender" in p for p in probs), probs
    print("Selbstprüfung Daytrading/Kongress: OK")


def save_samples():
    sample = ROOT / "docs" / "sample"
    sample.mkdir(parents=True, exist_ok=True)
    dt_store = TMP / "public"
    for name in ("setups", "entries", "orb"):
        shutil.copy(dt_store / f"{name}.json", sample / f"{name}.json")
    st = json.loads((dt_store / "status.json").read_text())
    (sample / "status-daytrade.json").write_text(json.dumps(dict(st, errors=[], ok=True), ensure_ascii=False, indent=1))
    if (sample / "tm").exists():
        shutil.rmtree(sample / "tm")
    shutil.copytree(dt_store / "tm", sample / "tm")
    shutil.copy(TMP / "congress" / "public" / "congress.json", sample / "congress.json")
    cst = json.loads((TMP / "congress" / "public" / "status.json").read_text())
    (sample / "status-congress.json").write_text(json.dumps(cst, ensure_ascii=False, indent=1))
    print(f"Beispieldaten für die Web-App: {sample}")


def main():
    sent = []
    notify.send = lambda title, msg, **kw: sent.append((title, msg, kw)) or True
    test_daytrade(sent)
    test_session_loop()
    test_selfcheck()
    test_congress(sent)
    save_samples()
    print("\nAlle Daytrading- und Kongress-Tests bestanden.")


if __name__ == "__main__":
    main()
