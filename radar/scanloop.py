"""Scan-Schleife: ein Workflow-Lauf scannt alle 5 Minuten, solange eine Börse offen ist.

Hintergrund: GitHub startet die Cron-Jobs ("*/5") oft nur ein- bis fünfmal am Tag und mit
Stunden Verspätung. Deshalb hält ein einzelner Lauf jetzt bis zu ~5,5 Std. durch, veröffentlicht
nach jedem Scan (radar/gitstore.py) und startet vor Ablauf selbst den Nachfolger
(workflow_dispatch). Die Cron-Einträge sind nur noch der Starter.

Weil GitHub den Morgen-Cron teils erst am Nachmittag startet (19.11.: erster Lauf 15:21 UTC,
Xetra blieb ungescannt), überbrückt die Kette werktags auch die Nacht: Ist die nächste Eröffnung
höchstens OVERNIGHT_BRIDGE entfernt, wartet der Lauf und startet vor Ablauf den Nachfolger.
Vor dem Wochenende endet die Kette und übergibt an den Weckdienst (wake.yml, eigene
Concurrency-Gruppe, blockiert also Wochenlauf & Co. nicht): Er wartet in Etappen bis kurz vor
der nächsten Eröffnung und startet dann scan.yml – denn auch der Montags-Cron kam am 23.11.
erst um 17:32 UTC, Xetra blieb ungescannt.

Weil die Schleife die Concurrency-Gruppe "radar-store" belegt, übernimmt sie auch den
Tageslauf (falls heute noch keiner lief), die Selbstprüfung zu den Zeiten von health.yml und stößt den Daytrading-Lauf an, falls GitHub
dessen Cron verschlafen hat. Alarm- und Bewertungslogik bleiben unverändert (jobs.scan).
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from . import gitstore, jobs, store
from .market_hours import MARKETS, is_open, local_now, utcnow

STEP_MINUTES = 5
WAIT_FOR_OPEN = timedelta(minutes=120)        # so lange vor Börsenstart wartet die Schleife
SELFCHECK_SLOTS_UTC = ((12, 7), (18, 7))      # wie in .github/workflows/health.yml
DAYTRADE_FROM_UTC = (12, 31)                  # erster Cron-Termin in daytrade.yml
DAYTRADE_UNTIL_UTC = (19, 0)
OVERNIGHT_BRIDGE = timedelta(hours=14)        # Abend -> nächster Morgen, nicht übers Wochenende


def minutes_to_next_open(now) -> float | None:
    """Minuten bis zur nächsten Eröffnung heute (0, wenn schon offen; None, wenn heute nichts mehr)."""
    best = None
    for m, spec in MARKETS.items():
        if is_open(m, now):
            return 0.0
        loc = local_now(m, now)
        if loc.weekday() >= 5:
            continue
        op = loc.replace(hour=spec["open"].hour, minute=spec["open"].minute, second=0, microsecond=0)
        if op > loc:
            mins = (op - loc).total_seconds() / 60
            best = mins if best is None else min(best, mins)
    return best


def minutes_to_next_open_any(now, days: int = 4) -> float | None:
    """Minuten bis zur nächsten Eröffnung irgendeiner Börse, auch an Folgetagen (0, wenn offen)."""
    best = None
    for m, spec in MARKETS.items():
        if is_open(m, now):
            return 0.0
        loc = local_now(m, now)
        for d in range(days + 1):
            day = loc + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            op = day.replace(hour=spec["open"].hour, minute=spec["open"].minute, second=0, microsecond=0)
            if op > loc:
                mins = (op - loc).total_seconds() / 60
                best = mins if best is None else min(best, mins)
                break
    return best


def bridging(now) -> bool:
    """Lohnt es, auf die nächste Eröffnung zu warten (über Nacht, aber nicht übers Wochenende)?"""
    nxt = minutes_to_next_open_any(now)
    return nxt is not None and nxt <= OVERNIGHT_BRIDGE.total_seconds() / 60


def next_tick(now) -> datetime:
    """Nächster 5-Minuten-Takt (plus ein paar Sekunden Puffer für die Kursdaten)."""
    base = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % STEP_MINUTES)
    nxt = base + timedelta(minutes=STEP_MINUTES, seconds=20)
    if nxt <= now:
        nxt += timedelta(minutes=STEP_MINUTES)
    return nxt


def _gh(method: str, path: str, **kw):
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", "")
    if "/" not in repo or not token:
        return None
    try:
        return requests.request(method, f"https://api.github.com/repos/{repo}/{path}", timeout=20,
                                headers={"Authorization": f"Bearer {token}",
                                         "Accept": "application/vnd.github+json"}, **kw)
    except requests.RequestException as exc:
        print(f"[scanloop] GitHub-API: {exc}")
        return None


def dispatch(workflow: str, inputs: dict | None = None) -> bool:
    r = _gh("POST", f"actions/workflows/{workflow}/dispatches", json={"ref": "main", "inputs": inputs or {}})
    ok = r is not None and r.status_code == 204
    print(f"[scanloop] {workflow} gestartet" if ok else
          f"[scanloop] {workflow} konnte nicht gestartet werden ({getattr(r, 'status_code', '-')})")
    return ok


def daytrade_ran_today(now) -> bool | None:
    """Gab es heute (UTC) schon einen Daytrading-Lauf ab dem ersten Cron-Termin? None = unbekannt."""
    since = now.replace(hour=DAYTRADE_FROM_UTC[0] - 1, minute=0, second=0, microsecond=0)
    r = _gh("GET", "actions/workflows/daytrade.yml/runs",
            params={"per_page": 20, "created": f">={since:%Y-%m-%dT%H:%M:%SZ}"})
    if r is None or not r.ok:
        return None
    return any(run.get("status") != "completed" or run.get("conclusion") == "success"
               for run in r.json().get("workflow_runs", []))


def daily_missing(now) -> bool:
    """Lief der Tageslauf (Basisdaten + Watchlist) heute (Berliner Datum) noch nicht?"""
    s = store.load("public", "status", {}) or {}
    last = s.get("watchlist_updated")
    if not last:
        return True
    return jobs._berlin_date(datetime.fromisoformat(last)) != jobs._berlin_date(now)


def _due(now, hm) -> bool:
    return now >= now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def session(provider, max_minutes: float = 330, now_fn=utcnow, sleep_fn=time.sleep,
            publish_fn=gitstore.publish, dispatch_fn=dispatch, daytrade_check=daytrade_ran_today,
            selfcheck_fn=None, daily_fn=None) -> dict:
    selfcheck_fn = selfcheck_fn or (lambda: jobs.selfcheck(push=True))
    daily_fn = daily_fn or (lambda: jobs.run_guarded("daily", jobs.daily, provider))
    start = now_fn()
    scans, errors = 0, 0
    # Prüftermine, die vor dem Start lagen, holt health.yml bzw. der Nachfolger nicht nach.
    done_slots = {(start.date(), s) for s in SELFCHECK_SLOTS_UTC if _due(start, s)}
    daytrade_checked = daily_tried = False
    while True:
        now = now_fn()
        wait = minutes_to_next_open(now)
        idle = wait is None or wait > WAIT_FOR_OPEN.total_seconds() / 60
        if idle and not bridging(now):
            if minutes_to_next_open_any(now) is not None:
                dispatch_fn("wake.yml")     # Wochenende: Weckdienst startet die Kette wieder
            return {"scans": scans, "errors": errors, "reason": "keine Börse mehr offen"}
        if idle:                        # Nacht überbrücken: nur warten, Nachfolger rechtzeitig starten
            wake = min(now + timedelta(minutes=30), start + timedelta(minutes=max_minutes))
            if wake >= start + timedelta(minutes=max_minutes):
                if bridging(wake):
                    dispatch_fn("scan.yml")
                return {"scans": scans, "errors": errors, "reason": "Laufzeit-Grenze erreicht, Nachfolger gestartet"}
            sleep_fn(max(1.0, (wake - now).total_seconds()))
            continue
        if not daily_tried and now.weekday() < 5 and daily_missing(now):
            daily_tried = True          # höchstens ein Versuch pro Lauf
            try:
                daily_fn()
            except Exception as exc:  # protokolliert; Scan baut Basisdaten notfalls selbst
                print(f"[scanloop] Tageslauf fehlgeschlagen: {type(exc).__name__}: {exc}")
            publish_fn("daily")
            now = now_fn()
        if wait == 0:
            try:
                jobs.run_guarded("scan", jobs.scan, provider, now=now)
            except Exception as exc:  # schon protokolliert und gemeldet – weiterscannen
                errors += 1
                print(f"[scanloop] Fehler im Scan: {type(exc).__name__}: {exc}")
            scans += 1
            publish_fn("scan")
        for slot in SELFCHECK_SLOTS_UTC:
            if (now.date(), slot) not in done_slots and _due(now, slot) and now.weekday() < 5:
                done_slots.add((now.date(), slot))
                try:
                    selfcheck_fn()
                except Exception as exc:
                    print(f"[scanloop] Selbstprüfung fehlgeschlagen: {exc}")
                publish_fn("selfcheck")
        if (not daytrade_checked and now.weekday() < 5 and _due(now, DAYTRADE_FROM_UTC)
                and not _due(now, DAYTRADE_UNTIL_UTC)):
            ran = daytrade_check(now)
            if ran is not None:
                daytrade_checked = True
                if not ran:
                    dispatch_fn("daytrade.yml")
        wake = next_tick(now_fn())
        if wake - start > timedelta(minutes=max_minutes):
            later = minutes_to_next_open(wake)
            if (later is not None and later <= WAIT_FOR_OPEN.total_seconds() / 60) or bridging(wake):
                dispatch_fn("scan.yml")
            return {"scans": scans, "errors": errors, "reason": "Laufzeit-Grenze erreicht, Nachfolger gestartet"}
        while True:
            left = (wake - now_fn()).total_seconds()
            if left <= 0:
                break
            sleep_fn(min(left, 600))


WAKE_LEAD = timedelta(minutes=110)            # so lange vor der Eröffnung startet der Weckdienst scan.yml


def wake(max_minutes: float = 330, now_fn=utcnow, sleep_fn=time.sleep, dispatch_fn=dispatch) -> dict:
    """Weckdienst (wake.yml): wartet bis kurz vor der nächsten Eröffnung und startet dann scan.yml.

    Läuft in eigener Concurrency-Gruppe und hält den Datenspeicher nicht. Reicht die Laufzeit nicht
    bis zum Weckzeitpunkt, startet er sich selbst als Nachfolger.
    """
    start = now_fn()
    nxt = minutes_to_next_open_any(start)
    if nxt is None:
        return {"reason": "keine Eröffnung in Sicht"}
    target = start + timedelta(minutes=nxt) - WAKE_LEAD
    limit = start + timedelta(minutes=max_minutes)
    if target > limit:
        while now_fn() < limit:
            sleep_fn(min(600.0, max(1.0, (limit - now_fn()).total_seconds())))
        dispatch_fn("wake.yml")
        return {"reason": "Laufzeit-Grenze erreicht, Weckdienst-Nachfolger gestartet"}
    while now_fn() < target:
        sleep_fn(min(600.0, max(1.0, (target - now_fn()).total_seconds())))
    dispatch_fn("scan.yml")
    return {"reason": "scan.yml gestartet"}
