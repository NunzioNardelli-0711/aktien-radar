"""Live-Rauchtest der Daytrading- und Kongress-Module gegen die echten Datenquellen.

Läuft in einem leeren, temporären Datenspeicher, sendet keine Push-Nachrichten und
veröffentlicht nichts. Ergebnis: smoke-report.json (+ Zusammenfassung im Log).
Aufruf: python -m radar smoke
"""
import json
import os
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="radar-smoke-"))
    os.environ["RADAR_STORE"] = str(tmp)
    os.environ["NTFY_TOPIC"] = ""
    os.environ.pop("RADAR_PUBLISH", None)
    from . import config
    config.STORE, config.STATE, config.PUBLIC = tmp, tmp / "state", tmp / "public"
    config.NTFY_TOPIC = ""
    from . import congress, daytrade, notify, store
    from .vendor.daytrader import entry as E, scan as S, timemachine as TM

    pushes = []
    notify.send = lambda title, msg, **kw: pushes.append({"title": title, "message": msg, **kw}) or True
    report = {"started": datetime.now().astimezone().isoformat(), "steps": {}, "ok": True}

    def step(name, fn):
        t0 = time.monotonic()
        try:
            out = fn()
            report["steps"][name] = {"ok": True, "seconds": round(time.monotonic() - t0, 1), "result": out}
        except Exception as exc:
            report["ok"] = False
            report["steps"][name] = {"ok": False, "seconds": round(time.monotonic() - t0, 1),
                                     "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
        print(f"== {name}: {'OK' if report['steps'][name]['ok'] else 'FEHLER'} "
              f"({report['steps'][name]['seconds']} s)", flush=True)

    net = daytrade.YahooNet()

    def universe():
        u = daytrade.ensure_universe(net, daytrade.utcnow(), force=True)
        return {"symbols": len(u["symbols"]), "counts": u.get("counts"), "files": u.get("files_created"),
                "beispiele": u["symbols"][:3]}

    def cycle():
        r = daytrade.cycle(net, daytrade.utcnow())
        st = store.load("public", "status")
        se = store.load("public", "setups") or {}
        en = store.load("public", "entries") or {}
        orb = store.load("public", "orb") or {}
        return {"cycle": r, "status": {k: st.get(k) for k in ("phase", "message", "watch", "entries_triggered",
                                                                 "orb_hits", "cycle_seconds")},
                "setups": {k: se.get(k) for k in ("as_of", "universe", "fetched", "scanned", "failed",
                                                  "hits_total", "per_setup", "orb_universe", "watch")},
                "entries": [{k: e.get(k) for k in ("symbol", "status", "reason", "trigger", "plan", "tm")}
                            for e in en.get("items", [])],
                "orb": {"counts": orb.get("counts"), "hits": len(orb.get("hits", [])),
                        "erste": [(h["symbol"], h["time_et"], h["price"], (h.get("tm") or {}).get("verdict"))
                                  for h in orb.get("hits", [])[:10]]}}

    def second_cycle():
        net.new_cycle()
        r = daytrade.cycle(net, daytrade.utcnow())
        return {"cycle": r, "message": store.load("public", "status").get("message")}

    def time_machine_history():
        """Time Machine auf dem letzten vollständigen Handelstag (unabhängig von der Uhrzeit)."""
        sym = "TSLA"
        text = net.chart_text(sym, "60d")
        ch = E.parse_chart(text, sym)
        days = sorted({S.ts_to_eastern(b["t"]).date() for b in ch["bars"]})
        today = daytrade.et_of(daytrade.utcnow()).date()
        for d in reversed([x for x in days if x < today]):
            now = S.eastern_to_utc(datetime.combine(d, datetime.strptime("16:05", "%H:%M").time()))
            res = E.evaluate(ch, now, setup="orb", or_minutes=15, interval="5m",
                             cfg={"no_entries_before": "09:45", "no_entries_after": "15:30"})
            if res["status"] == "triggered":
                t, orr = res["trigger"], res["opening_range"]
                plan = daytrade.make_plan(sym, d.isoformat(), t["price"], t["time"], orr["high"], orr["low"])
                doc = TM.time_machine(text, plan, now, 10000, 19, 2, "15:55")
                return {"date": d.isoformat(), "entry": plan["entry"], "entry_time": plan["entry_time"],
                        "stop": plan["stop"], "target": plan["target"],
                        "p_target": doc["mc"]["p_target"], "p_stop": doc["mc"]["p_stop"],
                        "p_neither": doc["mc"]["p_neither"], "pool_sessions": doc["mc"]["pool_sessions"],
                        "verdict": daytrade.verdict_de(doc["mc"]),
                        "history": {k: doc["history"][k] for k in ("sessions", "triggered", "target", "stop")}}
        return {"hinweis": "TSLA hat in den letzten Tagen kein ORB-Signal gehabt"}

    def kongress():
        cstore = tmp / "congress"
        config.STORE, config.STATE, config.PUBLIC = cstore, cstore / "state", cstore / "public"
        old = config.CONGRESS_FIRST_RUN_DAYS
        config.CONGRESS_FIRST_RUN_DAYS = 7
        try:
            r = congress.run(push=False)
        finally:
            config.CONGRESS_FIRST_RUN_DAYS = old
            config.STORE, config.STATE, config.PUBLIC = tmp, tmp / "state", tmp / "public"
        pub = json.loads((cstore / "public" / "congress.json").read_text())
        fil = pub["filings"]
        return {"run": r, "filings": len(fil), "lesbar": sum(1 for f in fil if f["readable"]),
                "zeilen": sum(len(f["rows"]) for f in fil),
                "beispiele": [(f["last"], f["filed"], [(x["type_de"], x["ticker"], congress.amount_de(x))
                                                      for x in f["rows"][:3]]) for f in fil[:6]],
                "top": [(t["ticker"], t["kaeufe"], t["verkaeufe"]) for t in pub["top"][:8]]}

    step("universum", universe)
    step("takt_1_vorboerse_orb_entry", cycle)
    step("takt_2", second_cycle)
    step("time_machine_letzter_handelstag", time_machine_history)
    step("kongress", kongress)
    report["pushes_simuliert"] = pushes
    report["finished"] = datetime.now().astimezone().isoformat()
    Path("smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: (v if k != "steps" else {n: {kk: vv for kk, vv in s.items() if kk != "trace"}
                                                  for n, s in v.items()})
                      for k, v in report.items() if k != "pushes_simuliert"},
                     ensure_ascii=False, indent=1, default=str)[:20000])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
