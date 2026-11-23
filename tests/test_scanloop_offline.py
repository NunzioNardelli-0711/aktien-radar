"""Scan-Schleife (radar/scanloop.py) mit simulierter Uhr – ohne Internet.

Aufruf:  python tests/test_scanloop_offline.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["RADAR_STORE"] = tempfile.mkdtemp(prefix="radar-loop-")
os.environ["NTFY_TOPIC"] = ""
sys.path.insert(0, str(ROOT))

from radar import jobs, scanloop, store  # noqa: E402


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


def run(start, max_minutes=330, daytrade_ran=False, watchlist_today=True):
    clock = Clock(start)
    log = {"scan": [], "publish": [], "dispatch": [], "selfcheck": [], "daily": []}
    if watchlist_today:
        store.save("public", "status", {"watchlist_updated": start.isoformat()})
    else:
        store.save("public", "status", {"watchlist_updated": (start - timedelta(days=1)).isoformat()})
    jobs.scan = lambda provider, now=None: log["scan"].append(now)
    res = scanloop.session(
        None, max_minutes=max_minutes, now_fn=clock.now, sleep_fn=clock.sleep,
        publish_fn=lambda label: log["publish"].append(label),
        dispatch_fn=lambda wf: log["dispatch"].append(wf) or True,
        daytrade_check=lambda now: daytrade_ran,
        selfcheck_fn=lambda: log["selfcheck"].append(clock.now()),
        daily_fn=lambda: log["daily"].append(clock.now()))
    return res, log, clock


def main():
    # Mi 18.11.2026 (Winterzeit): Xetra 08:00–16:30 UTC, US 14:30–21:00 UTC
    res, log, clock = run(datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc))
    print("Lauf 1:", res, len(log["scan"]), "Scans", log["dispatch"])
    first = log["scan"][0]
    assert first.hour == 8 and first.minute == 0, first           # wartet bis Xetra-Start
    gaps = {(b - a) for a, b in zip(log["scan"], log["scan"][1:])}
    assert gaps == {timedelta(minutes=5)}, gaps                     # lückenlos alle 5 Minuten
    assert log["dispatch"] == ["scan.yml"], log["dispatch"]         # Nachfolger gestartet
    assert len(log["selfcheck"]) == 1 and log["selfcheck"][0].hour == 12, log["selfcheck"]
    assert not log["daily"]
    assert clock.now() - datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc) <= timedelta(minutes=331)

    # Nachfolger ab 12:30 bis Börsenschluss US (21:00 UTC), Daytrading lief heute noch nicht
    res, log, clock = run(datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc), max_minutes=600,
                          daytrade_ran=False, watchlist_today=False)
    print("Lauf 2:", res, len(log["scan"]), "Scans", log["dispatch"])
    assert "Nachfolger" in res["reason"], res                    # überbrückt die Nacht
    assert log["scan"][-1] == datetime(2026, 11, 18, 20, 55, 20, tzinfo=timezone.utc), log["scan"][-1]
    assert log["dispatch"] == ["daytrade.yml", "scan.yml"], log["dispatch"]  # verschlafenen Daytrading-Lauf angestoßen
    assert [t.hour for t in log["selfcheck"]] == [18]               # 12:07 lag vor dem Start
    assert len(log["daily"]) == 1                                   # Tageslauf nachgeholt

    # Nacht werktags: warten, ohne zu scannen, und rechtzeitig den Nachfolger starten
    res, log, clock = run(datetime(2026, 11, 18, 21, 30, tzinfo=timezone.utc), watchlist_today=True)
    assert not log["scan"] and not log["daily"] and log["dispatch"] == ["scan.yml"], (res, log)
    assert clock.now() <= datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc), clock.now()
    res, log, clock = run(datetime(2026, 11, 19, 2, 20, tzinfo=timezone.utc))
    assert not log["scan"] and log["dispatch"] == ["scan.yml"], (res, log)
    # Nachfolger am Morgen: Tageslauf vor Xetra-Start, erster Scan 08:00 UTC
    res, log, clock = run(datetime(2026, 11, 19, 7, 50, tzinfo=timezone.utc), watchlist_today=False)
    assert len(log["daily"]) == 1 and log["scan"][0].hour == 8 and log["scan"][0].minute == 0, log
    assert len(log["selfcheck"]) == 1 and log["selfcheck"][0].hour == 12, log["selfcheck"]
    print("Nacht-Überbrückung: ok")

    # Freitagabend / Wochenende: sofort beenden
    for t in (datetime(2026, 11, 20, 21, 30, tzinfo=timezone.utc), datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)):
        res, log, _ = run(t)
        assert not log["scan"] and res["reason"] == "keine Börse mehr offen", (t, res)
        assert log["dispatch"] == ["wake.yml"], (t, log["dispatch"])   # Weckdienst übernimmt

    # Weckdienst: Fr 21:00 UTC -> Etappen bis Mo 06:10 UTC, dann scan.yml (Xetra 08:00 UTC)
    t = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
    hops = 0
    while True:
        clock, sent = Clock(t), []
        res = scanloop.wake(max_minutes=330, now_fn=clock.now, sleep_fn=clock.sleep,
                            dispatch_fn=lambda wf: sent.append(wf) or True)
        assert len(sent) == 1, sent
        hops += 1
        t = clock.now()
        if sent == ["scan.yml"]:
            break
        assert sent == ["wake.yml"] and hops < 20, (sent, hops)
    assert t == datetime(2026, 11, 23, 6, 10, tzinfo=timezone.utc), t
    res, log, _ = run(t, watchlist_today=False)                 # Montag: Kette läuft ab Xetra-Start
    assert log["scan"][0] == datetime(2026, 11, 23, 8, 0, 20, tzinfo=timezone.utc), log["scan"][0]
    print(f"Weckdienst: ok ({hops} Etappen)")
    print("Scan-Schleife: alle Tests bestanden.")


if __name__ == "__main__":
    main()
