"""Daytrading-Module für US-Aktien, aufgebaut auf den Werkzeugen aus day-trader-skill:

* Setup-Scanner (scan.py): vor Börsenstart alle ~5.900 US-Aktien nach Tages-Setups
  durchsuchen (20-Tage-Ausbruch, Bullenflagge, Erholung aus überverkauft …) und
  während der Sitzung Opening-Range-Breakouts (ORB) im liquiden Teil finden.
* Entry-Timer (entry.py): die besten Setups Kerze für Kerze beobachten und den
  Einstiegszeitpunkt melden (erste 5-Min.-Kerze, die über der Eröffnungsspanne schließt).
* Time Machine (timemachine.py): jeden Einstieg 10.000-mal aus den 5-Min.-Kerzen der
  letzten ~60 Tage durchspielen und prüfen, wie oft dieselbe Regel früher funktioniert hat.

Alle Zeiten im Handel sind New Yorker Zeit (ET). Die Werkzeuge arbeiten mit
"naiver" UTC-Zeit; die Umrechnung passiert hier. Es wird nie eine Order platziert.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, gitstore, notify, store
from .vendor.daytrader import entry as E
from .vendor.daytrader import scan as S
from .vendor.daytrader import timemachine as TM

VERSION = "1.0.0"
BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
MIN_UNIVERSE = 1000      # weniger Aktien in der Nasdaq-Liste = Download kaputt, alte Liste behalten

SETUP_DE = {
    "breakout_20d": "Ausbruch über 20-Tage-Hoch",
    "bull_flag": "Bullenflagge",
    "reclaim_ma20": "Zurück über 20-Tage-Linie",
    "oversold": "Überverkauft (RSI < 30)",
    "oversold_bounce": "Erholung aus überverkauft",
    "orb": "Opening-Range-Breakout",
}
STATUS_DE = {"waiting": "wartet", "triggered": "Einstieg ausgelöst", "expired": "verfallen",
             "no-data": "keine Daten", "error": "Fehler"}
DISCLAIMER = ("Regelbasierte Signale aus freien, teils verzögerten Daten. Keine Anlageberatung, es wird "
              "nichts gekauft. Daytrading verliert bei den meisten Menschen Geld.")


# --------------------------------------------------------------------------
# Zeit
# --------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def naive(now: datetime) -> datetime:
    """Aware -> naive UTC (Format der day-trader-Werkzeuge)."""
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


def et_of(now: datetime) -> datetime:
    return S.to_eastern(naive(now))


def hhmm(text: str):
    return S.parse_hhmm(text, "Zeit")


def berlin_clock(day: str, et_hm: str) -> str:
    """'2026-10-19', '10:15' (New York) -> '16:15' (Berlin)."""
    t = datetime.fromisoformat(f"{day}T{et_hm}").replace(tzinfo=NEW_YORK)
    return t.astimezone(BERLIN).strftime("%H:%M")


def de(x, digits: int = 2) -> str:
    return "–" if x is None else f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct_de(x, digits: int = 0) -> str:
    return "–" if x is None else f"{x * 100:.{digits}f} %".replace(".", ",")


def entry_window(day):
    """(frühester, spätester) Einstieg als naive ET-Zeit; berücksichtigt verkürzte Handelstage."""
    sess = S.session(day)
    close_dt = datetime.combine(day, sess[1])
    before = datetime.combine(day, hhmm(config.DT_NO_ENTRIES_BEFORE))
    after = E.early_cutoff(day, hhmm(config.DT_NO_ENTRIES_AFTER), close_dt)
    return before, after


# --------------------------------------------------------------------------
# Datenquelle (Yahoo + Nasdaq Trader); die Tests ersetzen diese Klasse
# --------------------------------------------------------------------------
class YahooNet:
    def __init__(self, pause: float = config.DT_PAUSE):
        self.pause = pause
        self._cache: dict[str, str] = {}
        S.SLEEP = time.sleep

    def new_cycle(self):
        self._cache = {}

    def nasdaq_files(self) -> dict[str, str]:
        out = {}
        for f in S.NASDAQ_FILES:
            out[f] = S.http_get(S.NASDAQ_URL + f, timeout=60)
            time.sleep(self.pause)
        return out

    def spark(self, symbols, rng, interval):
        return S.fetch_spark(list(symbols), rng, interval, self.pause)

    def chart_text(self, sym: str, rng: str) -> str:
        """Yahoo-v8-Chart mit 5-Min.-Kerzen; innerhalb eines Takts zwischengespeichert."""
        path = S.chart_path(sym, rng, "5m")
        if path not in self._cache:
            if self.pause:
                time.sleep(self.pause)
            self._cache[path] = S.yahoo_get(path)
        return self._cache[path]


# --------------------------------------------------------------------------
# Universum: US-Stammaktien laut Nasdaq Trader
# --------------------------------------------------------------------------
def ensure_universe(net, now, force: bool = False) -> dict:
    uni = store.load("state", "dt_universe")
    if uni and uni.get("symbols") and not force:
        age = now - datetime.fromisoformat(uni["updated"])
        if age < timedelta(days=config.DT_UNIVERSE_MAX_AGE_DAYS):
            return uni
    try:
        kept, counts, created = S.build_universe(net.nasdaq_files())
        if len(kept) < MIN_UNIVERSE:
            raise ValueError(f"nur {len(kept)} Aktien in der Nasdaq-Trader-Liste")
        uni = {"updated": now.isoformat(), "symbols": kept, "counts": counts, "files_created": created}
        store.save("state", "dt_universe", uni)
        return uni
    except Exception as exc:  # Quelle down: alte Liste weiterverwenden
        print(f"[daytrade] Universum nicht aktualisiert: {exc}")
        if uni and uni.get("symbols"):
            return uni
        radar = store.load("state", "universe", {}) or {}
        fallback = [[t["symbol"], t["name"]] for t in radar.get("tickers", []) if t.get("market") == "US"]
        if not fallback:
            raise RuntimeError(f"Kein US-Aktienuniversum verfügbar ({exc})")
        return {"updated": now.isoformat(), "symbols": fallback, "counts": {"fallback": len(fallback)}}


def clean_name(name: str) -> str:
    """'Tesla, Inc. - Common Stock' -> 'Tesla, Inc.'"""
    n = re.split(r" - |\s+(?:Class [A-Z] )?(?:Common Stock|Common Shares|Ordinary Shares|American Depositary)",
                 name or "")[0]
    return n.strip().rstrip(",") or name


def _extra_watch() -> list[str]:
    p = config.ROOT / "config" / "daytrade_watch.txt"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.split("#")[0].strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def _rank(hit: dict):
    prio = [config.DT_SETUP_PRIORITY.index(t) for t in hit["setups"] if t in config.DT_SETUP_PRIORITY]
    return (min(prio) if prio else 99, -len(hit["setups"]), -(hit.get("value") or 0), hit["symbol"])


def choose_watch(hits: list[dict], extra: list[str], names: dict | None = None) -> list[dict]:
    by_sym = {h["symbol"]: h for h in hits}
    watch = []
    for sym in extra:
        h = by_sym.get(sym, {})
        watch.append({"symbol": sym, "name": h.get("name") or (names or {}).get(sym, sym), "source": "eigene Liste",
                      "setups": h.get("setups", [])})
    for h in sorted(hits, key=_rank):
        if len(watch) >= config.DT_ENTRY_WATCH_MAX:
            break
        if all(w["symbol"] != h["symbol"] for w in watch):
            watch.append({"symbol": h["symbol"], "name": h["name"], "source": "Setup-Scanner",
                          "setups": h["setups"]})
    return watch


# --------------------------------------------------------------------------
# Vor Börsenstart: Tages-Setups
# --------------------------------------------------------------------------
def premarket(net, now) -> dict:
    nn = naive(now)
    today = S.to_eastern(nn).date()
    uni = ensure_universe(net, now)
    names = {s: clean_name(n) for s, n in uni["symbols"]}
    symbols = list(names)
    data, failed = net.spark(symbols, "3mo", "1d")
    if symbols and len(data) < len(symbols) * 0.5:
        raise RuntimeError(f"Setup-Scanner: nur {len(data)} von {len(symbols)} Tagescharts geladen "
                           "(Yahoo-Rate-Limit?)")
    hits, counts, last_date = S.scan_daily(data, symbols, nn, config.DT_DAILY_MIN_PRICE,
                                           config.DT_DAILY_MIN_VOLUME)
    for h in hits:
        meta = data[h["symbol"]].get("meta") or {}
        h["name"] = names.get(h["symbol"]) or meta.get("longName") or h["symbol"]
        h["value"] = round(h["price"] * (h.get("volume") or 0))
        h["labels"] = [SETUP_DE.get(t, t) for t in h["setups"]]

    liquid = []
    for sym, ser in data.items():
        m = ser.get("meta") or {}
        p, v = m.get("regularMarketPrice"), m.get("regularMarketVolume")
        if p and v and p >= config.DT_ORB_MIN_PRICE and v >= config.DT_ORB_MIN_PREV_VOLUME:
            liquid.append((sym, p * v))
    liquid.sort(key=lambda x: -x[1])

    watch = choose_watch(hits, _extra_watch(), names)
    day = {"date": today.isoformat(), "created": now.isoformat(), "orb_symbols": [s for s, _ in liquid],
           "names": {h["symbol"]: h["name"] for h in hits} | {w["symbol"]: w["name"] for w in watch},
           "watch": watch, "entries": {}, "orb_hits": {}, "orb_last": None, "orb_counts": None,
           "tm_orb": [], "pushes": 0}
    store.save("state", "dt_day", day)
    per_setup = {k: sum(1 for h in hits if k in h["setups"]) for k, _ in S.SETUPS}
    store.save("public", "setups", {
        "date": today.isoformat(), "updated": now.isoformat(),
        "as_of": last_date.isoformat() if last_date else None,
        "universe": len(symbols), "fetched": counts["fetched"], "scanned": counts["scanned"],
        "failed": len(failed), "filters": {"min_price": config.DT_DAILY_MIN_PRICE,
                                           "min_volume": config.DT_DAILY_MIN_VOLUME},
        "per_setup": {SETUP_DE[k]: n for k, n in per_setup.items()}, "hits_total": len(hits),
        "hits": sorted(hits, key=_rank)[:200], "watch": [w["symbol"] for w in watch],
        "orb_universe": len(liquid),
        "hinweis": "Ein Scan ist eine Liste von Charts, die eine Regel erfüllen – keine Kaufliste.",
    })
    print(f"[daytrade] Setups: {len(hits)} Treffer aus {counts['scanned']} Charts, "
          f"{len(watch)} beobachtet, {len(liquid)} im ORB-Scan")
    return day


# --------------------------------------------------------------------------
# Time Machine
# --------------------------------------------------------------------------
def verdict_de(mc: dict) -> str:
    lv = TM.lean(mc)
    if lv is None:
        return "Kein Durchlauf erreichte Ziel oder Stop – der Kurs am Ende entscheidet."
    d, share, even = lv
    one_r = abs((mc.get("r_at_target") or 1.0) - 1.0) < 0.005
    if abs(d) < TM.COIN_FLIP:
        return "Etwa ein Münzwurf" if one_r else "Etwa Gleichstand"
    if abs(d) < TM.STRONG:
        return "Tendenz zum Ziel" if d > 0 else "Tendenz zum Stop"
    return "Deutlich Richtung Ziel" if d > 0 else "Deutlich Richtung Stop"


def make_plan(sym: str, day: str, price: float, entry_time: str, or_high: float, or_low: float) -> dict:
    """Ausstiegsplan wie im trader-exit-Beispiel: Stop in der Mitte der Spanne, Ziel 1R, glatt bis 15:55."""
    stop = TM.cents_away((or_high + or_low) / 2, True)
    if price - stop < 0.02:            # sehr enge Spanne: mindestens 1 % Abstand
        stop = TM.cents_away(price * 0.99, True)
    target = round(price + config.DT_TARGET_R * (price - stop), 2)
    raw = {"symbol": sym, "side": "buy", "date": day, "entry": price, "stop": stop, "target": target,
           "entry_time": entry_time, "setup": "orb", "opening_range": {"minutes": config.DT_ORB_MINUTES},
           "stop_rule": "or_mid", "interval": "5m", "flat_by": config.DT_FLAT_BY}
    return TM.normalize_plan(raw, "aktien-radar")


def run_time_machine(net, plan: dict, now, kind: str) -> dict:
    """Plan durchspielen, Detail speichern, Kurzfassung zurückgeben (oder {'error': …})."""
    tm_id = f"{plan['date'].replace('-', '')}-{plan['symbol']}-{kind}"
    try:
        text = net.chart_text(plan["symbol"], "60d")
        doc = TM.time_machine(text, plan, naive(now), config.DT_TM_REPLAYS, config.DT_TM_SEED, 2,
                              config.DT_FLAT_BY)
    except (TM.TMError, S.ScanError) as exc:
        print(f"[daytrade] Time Machine {plan['symbol']}: {exc}")
        return {"error": str(exc)}
    mc, hist = doc["mc"], doc["history"]
    summary = {
        "id": tm_id, "p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"],
        "p_green": mc["p_green"], "avg_R": mc["avg_R"], "median_close": mc["median_close"],
        "p5_close": mc["p5_close"], "p95_close": mc["p95_close"], "until": mc["until"],
        "replays": mc["replays"], "pool_sessions": mc["pool_sessions"],
        "verdict": verdict_de(mc), "verdict_en": doc["verdict"],
        "history": {k: hist.get(k) for k in ("sessions", "triggered", "target", "stop", "close", "avg_R")},
    }
    detail = dict(doc, mc={k: v for k, v in mc.items() if k != "sample_paths"}, summary=summary,
                  kind=kind, disclaimer=DISCLAIMER)
    store.save("public", f"tm/{tm_id}", detail)
    return summary


# --------------------------------------------------------------------------
# Während der Sitzung
# --------------------------------------------------------------------------
def _entry_reason(res: dict) -> str:
    st, ph = res["status"], res.get("phase")
    lvl = res.get("level")
    if st == "triggered":
        t = res["trigger"]
        return f"Kerze {t['bar_start']} schloss bei {de(t['price'])} $ über dem Spannen-Hoch {de(lvl)} $"
    if st == "expired":
        return f"Kein Schluss über {de(lvl)} $ bis {res.get('no_entries_after', '15:30')} ET"
    if st == "no-data":
        return "Keine Kursdaten (Börse zu oder Yahoo liefert nichts)"
    if ph == "pre-open":
        return "Börse noch nicht offen"
    if ph == "forming":
        return "Eröffnungsspanne bildet sich (bis 9:45 ET)"
    last = res.get("last")
    if last and lvl:
        gap = lvl - last["close"]
        where = "unter" if gap >= 0 else "über"
        extra = " (vor 9:45 ET zählt nicht)" if gap < 0 else ""
        return (f"Letzter Schluss {de(last['close'])} $ ({last['bar_start']}), {de(abs(gap))} $ {where} "
                f"dem Spannen-Hoch {de(lvl)} $" + extra)
    return "wartet auf die nächste Kerze"


def check_entries(net, day: dict, now) -> list[dict]:
    """Entry-Timer für alle beobachteten Setups; liefert neu ausgelöste Einstiege."""
    nn = naive(now)
    cfg = {"no_entries_before": config.DT_NO_ENTRIES_BEFORE, "no_entries_after": config.DT_NO_ENTRIES_AFTER}
    fresh = []
    for w in day["watch"]:
        sym = w["symbol"]
        prev = day["entries"].get(sym, {})
        if prev.get("status") in ("triggered", "expired"):
            continue
        try:
            chart = E.parse_chart(net.chart_text(sym, "1d"), sym)
            res = E.evaluate(chart, nn, setup="orb", or_minutes=config.DT_ORB_MINUTES, interval="5m", cfg=cfg)
        except (E.EntryError, S.ScanError) as exc:
            day["entries"][sym] = dict(prev, status="error", reason=str(exc)[:200], checked=now.isoformat())
            continue
        orr = res.get("opening_range")
        item = {"symbol": sym, "status": res["status"], "status_de": STATUS_DE.get(res["status"], res["status"]),
                "reason": _entry_reason(res), "level": res.get("level"),
                "opening_range": {"high": orr["high"], "low": orr["low"]} if orr else None,
                "last": res.get("last"), "checked": now.isoformat(), "bars": res.get("bars_closed")}
        if res["status"] == "triggered":
            t = res["trigger"]
            item["trigger"] = {"time_et": t["close_time"], "time_berlin": berlin_clock(res["date"], t["close_time"]),
                               "bar_start": t["bar_start"], "price": t["price"], "pct_over": t["pct_over"],
                               "minutes_since": res.get("minutes_since")}
            try:
                plan = make_plan(sym, res["date"], t["price"], t["time"], orr["high"], orr["low"])
                item["plan"] = {k: plan[k] for k in ("entry", "stop", "target", "entry_time", "risk_per_share",
                                                     "target_r")}
                item["tm"] = run_time_machine(net, plan, now, "e")
            except TM.TMError as exc:
                item["tm"] = {"error": str(exc)}
            fresh.append(item)
        day["entries"][sym] = item
    return fresh


def _orb_due(day: dict, et: datetime) -> bool:
    if not day.get("orb_last"):
        return True
    last = S.to_eastern(naive(datetime.fromisoformat(day["orb_last"])))
    every = config.DT_ORB_EVERY_EARLY if et.time() < datetime.strptime("11:00", "%H:%M").time() \
        else config.DT_ORB_EVERY_LATE
    return (et - last) >= timedelta(minutes=every - 1)


def scan_orb(net, day: dict, now) -> list[dict]:
    """Opening-Range-Breakouts im liquiden Universum; liefert neue Treffer."""
    nn = naive(now)
    et = S.to_eastern(nn)
    at = (et - timedelta(seconds=40)).time().replace(second=0, microsecond=0)
    try:
        d, cutoff = S.orb_window(nn, at, config.DT_ORB_MINUTES, hhmm(config.DT_NO_ENTRIES_AFTER))
    except S.ScanError as exc:
        print(f"[daytrade] ORB-Scan übersprungen: {exc}")
        return []
    symbols = [s for s in day["orb_symbols"] if s not in day["orb_hits"]]
    if not symbols:
        return []
    stage1, failed = net.spark(symbols, "1d", "5m")

    def confirm(sym):
        return S.parse_chart(net.chart_text(sym, "1d"), sym)

    hits, counts, failed2 = S.scan_orb(stage1, symbols, d, cutoff, config.DT_ORB_MINUTES,
                                       config.DT_ORB_MIN_PRICE, 0, confirm, config.DT_ORB_MAX_CONFIRM)
    day["orb_last"] = now.isoformat()
    day["orb_counts"] = dict(counts, failed=len(failed) + len(failed2), as_of=cutoff.strftime("%H:%M"),
                             universe=len(day["orb_symbols"]))
    new = []
    for h in hits:
        meta = (stage1.get(h["symbol"]) or {}).get("meta") or {}
        value = (meta.get("regularMarketPrice") or h["price"]) * (meta.get("regularMarketVolume") or 0)
        at_et = datetime.strptime(h["at"], "%I:%M %p").strftime("%H:%M")
        item = {"symbol": h["symbol"], "name": day["names"].get(h["symbol"]) or meta.get("longName") or h["symbol"],
                "price": h["price"], "time_et": at_et, "time_berlin": berlin_clock(day["date"], at_et),
                "at": h["at"], "or_high": h["or_high"], "or_low": h["or_low"], "pct_over": h["pct_over"],
                "value": round(value), "found": now.isoformat()}
        day["orb_hits"][h["symbol"]] = item
        new.append(item)
    # Time Machine für die umsatzstärksten neuen Treffer
    for item in sorted(new, key=lambda x: -x["value"]):
        if len(day["tm_orb"]) >= config.DT_TM_ORB_TOP:
            break
        try:
            plan = make_plan(item["symbol"], day["date"], item["price"], item["at"], item["or_high"], item["or_low"])
            item["plan"] = {k: plan[k] for k in ("entry", "stop", "target", "entry_time", "risk_per_share", "target_r")}
            item["tm"] = run_time_machine(net, plan, now, "o")
        except TM.TMError as exc:
            item["tm"] = {"error": str(exc)}
        day["tm_orb"].append(item["symbol"])
    print(f"[daytrade] ORB {cutoff:%H:%M} ET: {counts['scanned']} geprüft, {len(new)} neue Treffer")
    return new


def entry_push(item: dict, day: dict) -> bool:
    w = next((x for x in day["watch"] if x["symbol"] == item["symbol"]), {})
    t, plan, tm = item["trigger"], item.get("plan") or {}, item.get("tm") or {}
    late = t.get("minutes_since") or 0
    title = f"🎯 Einstieg {item['symbol']} {de(t['price'])} $ · {t['time_et']} ET"
    lines = [f"{w.get('name', item['symbol'])}: Ausbruch über die Eröffnungsspanne ({de(item['level'])} $)"
             + (f" – {', '.join(SETUP_DE.get(s, s) for s in w.get('setups', []))}" if w.get("setups") else "")]
    if late > 7:
        lines.append(f"Hinweis: Signal liegt {late} Min. zurück – Kurs inzwischen {de((item.get('last') or {}).get('close'))} $")
    if plan:
        lines.append(f"Plan: Stop {de(plan['stop'])} · Ziel {de(plan['target'])} ({plan['target_r']:g}R) · "
                     f"glatt bis {config.DT_FLAT_BY} ET")
    if tm and not tm.get("error"):
        lines.append(f"Time Machine: Ziel zuerst {pct_de(tm['p_target'])} · Stop zuerst {pct_de(tm['p_stop'])} · "
                     f"offen {pct_de(tm['p_neither'])} → {tm['verdict']}")
        h = tm.get("history") or {}
        if h.get("triggered"):
            lines.append(f"Früher (60 Tage): {h['triggered']}× ausgelöst – {h['target']}× Ziel, {h['stop']}× Stop")
    lines.append(f"Uhrzeit bei dir: {t['time_berlin']} · keine Anlageberatung")
    url = config.app_url()
    click = (f"{url}#/tm/{tm['id']}" if tm.get("id") else f"{url}#/daytrade") if url else None
    return notify.send(title, "\n".join(lines), priority=4, tags=["dart"], click=click)


def publish_public(day: dict, now) -> None:
    order = {"triggered": 0, "waiting": 1, "error": 2, "no-data": 3, "expired": 4}
    items = []
    for w in day["watch"]:
        e = day["entries"].get(w["symbol"], {})
        items.append(dict(e, symbol=w["symbol"], name=w["name"], source=w["source"],
                          setups=[SETUP_DE.get(s, s) for s in w.get("setups", [])],
                          status=e.get("status", "waiting"), status_de=STATUS_DE.get(e.get("status", "waiting")),
                          reason=e.get("reason", "Beobachtung startet nach der Eröffnungsspanne (9:50 ET)")))
    items.sort(key=lambda x: (order.get(x["status"], 9), x["symbol"]))
    store.save("public", "entries", {"date": day["date"], "updated": now.isoformat(), "items": items,
                                     "window": [config.DT_NO_ENTRIES_BEFORE, config.DT_NO_ENTRIES_AFTER],
                                     "plan_rule": f"Stop = Mitte der Eröffnungsspanne, Ziel = {config.DT_TARGET_R:g}R, "
                                                  f"glatt bis {config.DT_FLAT_BY} ET",
                                     "disclaimer": DISCLAIMER})
    hits = sorted(day["orb_hits"].values(), key=lambda x: (x["time_et"], -x["value"]))
    store.save("public", "orb", {"date": day["date"], "updated": now.isoformat(), "counts": day.get("orb_counts"),
                                 "last_scan": day.get("orb_last"), "hits": hits,
                                 "regel": "Erste 5-Min.-Kerze, die über dem Hoch der ersten 15 Minuten schließt",
                                 "disclaimer": DISCLAIMER})


def _status(**kw) -> dict:
    s = store.load("public", "status", {}) or {}
    s.setdefault("errors", [])
    s.update(kw, version=VERSION, calendar_years=list(S.CALENDAR_YEARS))
    return s


def cycle(net, now) -> dict:
    """Ein Takt: ggf. Vorbörse-Scan, dann ORB-Scan und Entry-Timer, danach veröffentlichen."""
    t0 = time.monotonic()
    nn = naive(now)
    et = S.to_eastern(nn)
    today = et.date()
    if S.session(today) is None:
        s = _status(phase="closed", last_cycle=now.isoformat(),
                    message=f"Heute kein US-Handel ({S.trading_day(today)[1]})", ok=True)
        store.save("public", "status", s)
        return {"phase": "closed"}
    net.new_cycle()
    day = store.load("state", "dt_day")
    if not day or day.get("date") != today.isoformat():
        day = premarket(net, now)
    before, after = entry_window(today)
    first_bar = datetime.combine(today, S.OPEN) + timedelta(minutes=config.DT_ORB_MINUTES + 5)
    new_entries, new_orb = [], []
    if et >= first_bar:
        new_entries = check_entries(net, day, now)
        if et <= after + timedelta(minutes=1) and _orb_due(day, et):
            new_orb = scan_orb(net, day, now)
    for item in new_entries:
        if day["pushes"] < config.DT_MAX_ENTRY_PUSHES:
            item["pushed"] = entry_push(item, day)
            day["pushes"] += 1
    store.save("state", "dt_day", day)
    publish_public(day, now)
    phase = "pre-open" if et < first_bar else ("open" if et <= after else "after-cutoff")
    n_trig = sum(1 for e in day["entries"].values() if e.get("status") == "triggered")
    msg = {"pre-open": f"Setups bereit ({len(day['watch'])} beobachtet), Einstiege ab 9:50 New York",
           "open": f"{len(day['watch'])} Setups beobachtet, {n_trig} Einstiege, {len(day['orb_hits'])} ORB-Treffer",
           "after-cutoff": f"Einstiegsfenster vorbei: {n_trig} Einstiege, {len(day['orb_hits'])} ORB-Treffer"}[phase]
    s = _status(phase=phase, last_cycle=now.isoformat(), message=msg, ok=True, date=day["date"],
                watch=len(day["watch"]), entries_triggered=n_trig, orb_hits=len(day["orb_hits"]),
                orb_last=day.get("orb_last"), setups_date=day["date"],
                universe_updated=(store.load("state", "dt_universe", {}) or {}).get("updated"),
                universe_size=len((store.load("state", "dt_universe", {}) or {}).get("symbols", [])),
                cycle_seconds=round(time.monotonic() - t0, 1), app_url=config.app_url())
    store.save("public", "status", s)
    print(f"[daytrade] {et:%H:%M} ET – {msg}")
    return {"phase": phase, "new_entries": len(new_entries), "new_orb": len(new_orb)}


def _record_error(now, exc: Exception) -> None:
    s = _status(ok=False)
    s["errors"] = ([{"time": now.isoformat(), "job": "daytrade", "message": f"{type(exc).__name__}: {exc}"[:300]}]
                   + s["errors"])[:15]
    last = s.get("last_error_push")
    if not last or now - datetime.fromisoformat(last) > timedelta(hours=config.ERROR_PUSH_HOURS):
        url = config.app_url()
        if notify.send("⚠️ Daytrading: Fehler", f"{exc}"[:300], priority=3, tags=["warning"],
                       click=(url + "#/status") if url else None):
            s["last_error_push"] = now.isoformat()
    store.save("public", "status", s)


def next_wake(now) -> datetime:
    """Kurz nach dem nächsten 5-Min.-Kerzenschluss (Yahoo braucht ein paar Sekunden)."""
    et = et_of(now)
    step = config.DT_CYCLE_MINUTES
    base = et.replace(second=0, microsecond=0) - timedelta(minutes=et.minute % step)
    nxt = base + timedelta(minutes=step, seconds=45)
    if nxt <= et:
        nxt += timedelta(minutes=step)
    return now + (nxt - et)


def session(net, max_minutes: float = 330, now_fn=utcnow, sleep_fn=time.sleep, publish_fn=gitstore.publish) -> dict:
    """Schleife über die US-Sitzung bis kurz nach Ende des Einstiegsfensters (oder max_minutes)."""
    start = now_fn()
    errors_in_row, cycles = 0, 0
    while True:
        now = now_fn()
        et = et_of(now)
        sess = S.session(et.date())
        done = sess is None or et >= entry_window(et.date())[1] + timedelta(minutes=6)
        try:
            cycle(net, now)
            errors_in_row = 0
        except Exception as exc:  # protokollieren, melden, weitermachen
            errors_in_row += 1
            print(f"[daytrade] Fehler im Takt: {type(exc).__name__}: {exc}")
            _record_error(now, exc)
            if errors_in_row >= config.DT_MAX_CYCLE_ERRORS:
                publish_fn("daytrade")
                raise
        cycles += 1
        publish_fn("daytrade")
        if done:
            return {"cycles": cycles, "reason": "Sitzung beendet" if sess else "kein Handelstag"}
        wake = next_wake(now)
        if et < datetime.combine(et.date(), S.OPEN) + timedelta(minutes=config.DT_ORB_MINUTES + 5):
            first = datetime.combine(et.date(), S.OPEN) + timedelta(minutes=config.DT_ORB_MINUTES + 5, seconds=45)
            wake = now + (first - et)        # vor der ersten Einstiegskerze nichts zu tun
        if (wake - start) > timedelta(minutes=max_minutes):
            return {"cycles": cycles, "reason": "Laufzeit-Grenze erreicht, nächster Lauf übernimmt"}
        while True:
            left = (wake - now_fn()).total_seconds()
            if left <= 0:
                break
            sleep_fn(min(left, 600))
