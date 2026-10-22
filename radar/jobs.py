"""Die Aufgaben des Radars: Scan (alle 5 Min.), Tageslauf, Wochenlauf, Test-Alarm, Selbstprüfung."""
import os
import traceback
from datetime import datetime, timedelta, timezone

import requests

from . import analysis, baseline, config, fundamentals, notify, store, universe
from .indicators import safe
from .market_hours import (MARKETS, is_open, local_now, local_today, open_markets,
                           session_fraction, utcnow)

VERSION = "1.1.0"


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def _status() -> dict:
    s = store.load("public", "status", {}) or {}
    s.setdefault("errors", [])
    s["version"] = VERSION
    return s


def _berlin_date(now) -> str:
    return str(local_today("DE", now))


def run_guarded(job: str, fn, *args, **kwargs):
    """Fehler protokollieren, (gedrosselt) per Push melden und weiterreichen."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        now = utcnow()
        s = _status()
        s["errors"] = ([{"time": now.isoformat(), "job": job, "message": f"{type(exc).__name__}: {exc}"}]
                       + s["errors"])[:15]
        s["ok"] = False
        last = s.get("last_error_push")
        if not last or now - datetime.fromisoformat(last) > timedelta(hours=config.ERROR_PUSH_HOURS):
            if notify.send("⚠️ Aktien-Radar: Fehler", f"{job}: {exc}"[:300], priority=3, tags=["warning"],
                           click=(config.app_url() + "#/status") if config.app_url() else None):
                s["last_error_push"] = now.isoformat()
        store.save("public", "status", s)
        traceback.print_exc()
        raise


def _compact(a: dict) -> dict:
    keys = ("id", "symbol", "name", "market", "time", "price", "change_pct", "rel_vol", "score", "ampel")
    c = {k: a[k] for k in keys}
    c["grund"] = a["grund"]["label"]
    c["horizonte"] = {k: v["score"] for k, v in a["horizonte"].items()}
    c["live"] = a.get("live")
    return c


# --------------------------------------------------------------------------
# Scan alle 5 Minuten
# --------------------------------------------------------------------------
def scan(provider, now=None) -> dict:
    now = now or utcnow()
    started = datetime.now(timezone.utc)
    s = _status()
    uni = universe.ensure(provider)
    base, rebuilt = baseline.ensure(uni, provider, now)
    markets = open_markets(now)
    s.update({"last_run": now.isoformat(), "markets_open": markets,
              "universe_size": len(uni["tickers"]), "universe_updated": uni["updated"],
              "baseline_built": base["built"], "app_url": config.app_url()})
    if not markets:
        s["last_scan_result"] = "Börsen geschlossen – kein Scan nötig"
        s["ok"] = True
        store.save("public", "status", s)
        return {"hits": 0, "markets": []}

    meta = {t["symbol"]: t for t in uni["tickers"]}
    symbols = [sym for sym, t in meta.items() if t["market"] in markets and sym in base["items"]]
    hist = provider.history(symbols, period="5d")
    if symbols and not hist:
        raise RuntimeError("Datenquelle lieferte keine Kurse (Netzwerk oder Rate-Limit)")

    quotes = {}
    for sym in symbols:
        df = hist.get(sym)
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["Close"])
        if df.empty:
            continue
        mk = meta[sym]["market"]
        if df.index[-1].date() != local_today(mk, now):
            continue  # heute (noch) kein Handel, z. B. Feiertag
        b = base["items"][sym]
        if not b.get("prev_close") or not b.get("avg_vol20"):
            continue
        price = float(df["Close"].iloc[-1])
        vol = float(df["Volume"].iloc[-1] or 0)
        frac = max(session_fraction(mk, now), config.MIN_SESSION_FRACTION)
        quotes[sym] = {"price": price, "volume": vol,
                       "change_pct": (price / b["prev_close"] - 1) * 100,
                       "rel_vol": vol / (b["avg_vol20"] * frac)}

    hits = [sym for sym, q in quotes.items()
            if q["change_pct"] >= config.MIN_CHANGE_PCT and q["rel_vol"] >= config.MIN_REL_VOLUME
            and q["price"] >= config.MIN_PRICE
            and (base["items"][sym].get("turnover20") or 0) >= config.MIN_AVG_TURNOVER]

    today = _berlin_date(now)
    alerts = store.load("public", "alerts", {}) or {}
    if alerts.get("date") != today:
        alerts = {"date": today, "items": []}
    by_sym = {a["symbol"]: a for a in alerts["items"]}
    history = store.load("public", "history", []) or []
    fund = fundamentals.load()
    new_alerts = 0

    for sym in sorted(hits, key=lambda x: -quotes[x]["change_pct"]):
        q = quotes[sym]
        prev = by_sym.get(sym)
        live = {"price": safe(q["price"], 2), "change_pct": safe(q["change_pct"], 2),
                "rel_vol": safe(q["rel_vol"], 2), "time": now.isoformat()}
        if prev and q["change_pct"] - prev["change_pct"] < config.REALERT_EXTRA_PCT:
            prev["live"] = live  # nur aktualisieren, kein erneuter Push
            continue
        a = analysis.analyze(sym, meta[sym], base["items"][sym], q, fund, provider, now)
        a["live"] = live
        a["pushed"] = notify.alert_push(a)
        store.save("public", f"a/{a['id']}", a)
        c = _compact(a)
        by_sym[sym] = c
        history = [h for h in history if h["id"] != c["id"]]
        history.insert(0, c)
        new_alerts += 1

    # Live-Kurse bereits gemeldeter Aktien, die nicht mehr im Treffer sind, auffrischen
    for sym, c in by_sym.items():
        if sym in quotes and sym not in hits:
            q = quotes[sym]
            c["live"] = {"price": safe(q["price"], 2), "change_pct": safe(q["change_pct"], 2),
                         "rel_vol": safe(q["rel_vol"], 2), "time": now.isoformat()}

    alerts["items"] = sorted(by_sym.values(), key=lambda x: x["time"], reverse=True)
    alerts["updated"] = now.isoformat()
    store.save("public", "alerts", alerts)
    hist_ids = {c["id"]: c for c in alerts["items"]}
    history = [hist_ids.get(h["id"], h) for h in history][: config.HISTORY_MAX]
    store.save("public", "history", history)

    movers = sorted(({"symbol": sym, "name": meta[sym]["name"], "market": meta[sym]["market"],
                      "price": safe(q["price"], 2), "change_pct": safe(q["change_pct"], 2),
                      "rel_vol": safe(q["rel_vol"], 2), "alarm": sym in hits}
                     for sym, q in quotes.items()), key=lambda x: -x["change_pct"])[:15]
    store.save("public", "movers", {"updated": now.isoformat(), "markets": markets, "items": movers})

    dur = (datetime.now(timezone.utc) - started).total_seconds()
    s.update({"last_scan": now.isoformat(), "scanned": len(symbols), "quotes": len(quotes),
              "hits": len(hits), "new_alerts": new_alerts, "scan_seconds": round(dur, 1), "ok": True,
              "last_scan_result": (f"{len(quotes)} von {len(symbols)} Aktien geprüft, "
                                   f"{len(hits)} Treffer, {new_alerts} neue Alarme")
              if quotes else "Kein Handel heute (Feiertag?) oder noch keine Kurse"})
    if rebuilt:
        s["baseline_built"] = base["built"]
    store.save("public", "status", s)
    print(s["last_scan_result"])
    return {"hits": len(hits), "new": new_alerts, "markets": markets}


# --------------------------------------------------------------------------
# Tageslauf (vor Börsenstart)
# --------------------------------------------------------------------------
def daily(provider, now=None, push_digest: bool = True) -> dict:
    now = now or utcnow()
    s = _status()
    uni = universe.ensure(provider)
    base = baseline.build(uni, provider, now)
    if fundamentals.is_stale():
        fundamentals.build(uni, provider)
    wl = baseline.watchlist(uni, base, provider, now)
    _cleanup_details(now)

    if push_digest and wl["items"] and s.get("last_digest") != _berlin_date(now):
        lines = [f"• {w['symbol'].replace('.DE', '')}: {w['signals'][0]}" for w in wl["items"][:5]]
        url = config.app_url()
        notify.send(f"🔭 Frühwarn-Watchlist: {len(wl['items'])} Aktien", "\n".join(lines), priority=3,
                    tags=["telescope"], click=(url + "#/watch") if url else None)
        s["last_digest"] = _berlin_date(now)

    f = store.load("state", "fundamentals", {}) or {}
    s.update({"baseline_built": base["built"], "baseline_count": len(base["items"]),
              "baseline_failed": base["failed_count"], "watchlist_updated": wl["updated"],
              "watchlist_count": len(wl["items"]), "universe_size": len(uni["tickers"]),
              "universe_updated": uni["updated"], "universe_report": uni.get("report"),
              "fundamentals_updated": f.get("updated"), "app_url": config.app_url(), "ok": True})
    store.save("public", "status", s)
    print(f"Basisdaten: {len(base['items'])} Aktien, Watchlist: {len(wl['items'])}")
    return {"baseline": len(base["items"]), "watchlist": len(wl["items"])}


def weekly(provider) -> dict:
    uni = universe.ensure(provider, force=True)
    f = fundamentals.build(uni, provider)
    s = _status()
    s.update({"universe_size": len(uni["tickers"]), "universe_updated": uni["updated"],
              "universe_report": uni.get("report"), "fundamentals_updated": f["updated"]})
    store.save("public", "status", s)
    print(f"Universum: {len(uni['tickers'])}, Fundamentaldaten ok: {f['ok']}")
    return {"universe": len(uni["tickers"]), "fundamentals": f["ok"]}


def _cleanup_details(now, keep_days: int = 60):
    folder = config.PUBLIC / "a"
    if not folder.exists():
        return
    cutoff = (now - timedelta(days=keep_days)).strftime("%Y%m%d")
    for p in folder.glob("*.json"):
        if p.stem[:8] < cutoff:
            p.unlink()


# --------------------------------------------------------------------------
# Test-Alarm und Selbstprüfung
# --------------------------------------------------------------------------
def test_alert() -> bool:
    url = config.app_url()
    ok = notify.send("✅ Aktien-Radar ist verbunden",
                     "So sieht ein Alarm aus. Echte Alarme kommen mit höchster Priorität "
                     "auf den Sperrbildschirm. Tippen öffnet die App.",
                     priority=5, tags=["white_check_mark"], click=url or None)
    print("Test-Push gesendet" if ok else "Test-Push NICHT gesendet (NTFY_TOPIC prüfen)")
    return ok


def _branch_status(branch: str) -> dict | None:
    """status.json eines anderen Datenbranches (daytrade, congress) über GitHub lesen."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return None
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{repo}/{branch}/public/status.json",
                         params={"t": int(utcnow().timestamp())}, timeout=20)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def _check_daytrading(now, branch_status) -> list[str]:
    from .vendor.daytrader import scan as S
    problems = []
    et = S.to_eastern(now.astimezone(timezone.utc).replace(tzinfo=None))
    if et.year > max(S.CALENDAR_YEARS):
        problems.append(f"US-Feiertagskalender der Daytrading-Werkzeuge reicht nur bis {max(S.CALENDAR_YEARS)} "
                        "– radar/vendor/daytrader aktualisieren")
    dt = branch_status("daytrade")
    sess = S.session(et.date())
    if sess and dt is not None and et.time() >= datetime.strptime("10:05", "%H:%M").time():
        if dt.get("date") != et.date().isoformat():
            problems.append("Daytrading: heute noch kein Lauf (Setup-Scanner/Entry-Timer) – Workflow prüfen")
        elif et.time() <= datetime.strptime("15:30", "%H:%M").time() and dt.get("last_cycle"):
            a = now - datetime.fromisoformat(dt["last_cycle"])
            if a > timedelta(minutes=25):
                problems.append(f"Daytrading: letzter Takt vor {int(a.total_seconds() // 60)} Min. – Schleife läuft nicht")
    if dt:
        recent = [e for e in dt.get("errors", []) if now - datetime.fromisoformat(e["time"]) < timedelta(hours=24)]
        if len(recent) >= 3:
            problems.append(f"Daytrading: {len(recent)} Fehler in 24 Std., zuletzt: {recent[0]['message']}")
    cg = branch_status("congress")
    if cg and cg.get("congress_last"):
        a = now - datetime.fromisoformat(cg["congress_last"])
        if a > timedelta(days=3):
            problems.append(f"Kongress-Meldungen seit {a.days} Tagen nicht abgerufen – Workflow prüfen")
    if cg and len(cg.get("congress_errors") or []) >= 3:
        problems.append(f"Kongress: {len(cg['congress_errors'])} Meldung(en) nicht lesbar, z. B. {cg['congress_errors'][0]}")
    return problems


def selfcheck(now=None, push: bool = False, branch_status=None) -> list[str]:
    """Prüft, ob das System gesund läuft. Leere Liste = alles in Ordnung."""
    now = now or utcnow()
    s = store.load("public", "status", {}) or {}
    problems = []

    def age(key):
        return (now - datetime.fromisoformat(s[key])) if s.get(key) else None

    if any(is_open(m, now) and local_now(m, now) - local_now(m, now).replace(
            hour=MARKETS[m]["open"].hour, minute=MARKETS[m]["open"].minute) > timedelta(minutes=30)
           for m in MARKETS):
        a = age("last_scan")
        # GitHub startet Cron-Jobs oft nur alle 30–45 Minuten statt alle 5 – daher großzügige Schwelle
        if a is None or a > timedelta(minutes=60):
            problems.append(f"Letzter Scan vor {a} – Scanner läuft nicht regelmäßig")
    a = age("baseline_built")
    if now.weekday() < 5 and (a is None or a > timedelta(hours=30)):
        problems.append("Basisdaten älter als 30 Stunden – Tageslauf prüfen")
    if (s.get("universe_size") or 0) < 400:
        problems.append(f"Aktienuniversum zu klein ({s.get('universe_size')}) – Indexlisten prüfen")
    if (s.get("baseline_failed") or 0) > 80:
        problems.append(f"{s['baseline_failed']} Aktien ohne Kursdaten")
    a = age("fundamentals_updated")
    if a is None or a > timedelta(days=9):
        problems.append("Fundamentaldaten älter als 9 Tage – Wochenlauf prüfen")
    recent = [e for e in s.get("errors", []) if now - datetime.fromisoformat(e["time"]) < timedelta(hours=24)]
    if len(recent) >= 3:
        problems.append(f"{len(recent)} Fehler in den letzten 24 Stunden, zuletzt: {recent[0]['message']}")
    problems += _check_daytrading(now, branch_status or _branch_status)

    print("Selbstprüfung: OK" if not problems else "Selbstprüfung – Probleme:\n- " + "\n- ".join(problems))
    s["selfcheck"] = {"time": now.isoformat(), "problems": problems}
    store.save("public", "status", s)
    if push and problems:
        notify.send("🩺 Aktien-Radar: Wartung nötig", "\n".join(problems)[:500], priority=3, tags=["wrench"])
    return problems
