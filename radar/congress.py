"""Aktiengeschäfte von US-Abgeordneten (Repräsentantenhaus), aufgebaut auf ptr.py aus day-trader-skill.

Quelle ist das öffentliche Archiv des House Clerk: ein Jahresindex (ZIP mit XML) und je
Meldung ein PDF ("Periodic Transaction Report", PTR). Abgeordnete müssen Geschäfte über
1.000 $ binnen 45 Tagen melden (STOCK Act). Die Beträge sind Spannen, keine Preise.
Das ist öffentlich und kein Insiderwissen. Zum Lesen der PDFs wird `pdftotext` (poppler)
gebraucht; eingescannte Papiermeldungen lassen sich nicht lesen und erscheinen nur als Link.
"""
import re
import tempfile
from datetime import date, datetime, timedelta

from . import config, notify, store
from .vendor.daytrader import ptr as P

VERSION = "1.0.0"
TYPE_DE = {"P": "Kauf", "S": "Verkauf", "S (partial)": "Teilverkauf", "E": "Tausch"}
OWNER_DE = {"self": "selbst", "spouse": "Ehepartner", "joint": "gemeinsam", "dependent child": "Kind"}
ASSET_DE = {"ST": "Aktie", "OP": "Option", "GS": "Staatsanleihe", "CS": "Unternehmensanleihe",
            "EF": "Fonds/ETF", "MF": "Investmentfonds", "OT": "Sonstiges", "CT": "Krypto"}
HINWEIS = ("Öffentliche Pflichtmeldungen nach dem STOCK Act, bis zu 45 Tage nach dem Geschäft. "
           "Beträge sind Spannen. Kein Insiderwissen und keine Anlageberatung.")


class Net:
    """Netzwerkzugriff; die Tests ersetzen diese Klasse."""

    def index(self, year: int) -> list[dict]:
        return P.load_index(year)

    def read_ptr(self, doc_id: str, year: int, filed: str | None, folder: str):
        """-> Bericht (dict) oder None, wenn das PDF nicht lesbar ist (Scan, kein pdftotext)."""
        _, report = P._fetch_and_read(doc_id, year, folder, filed)
        return report


def _short(asset: str | None) -> str | None:
    """'Applied Materials, Inc. - Common Stock' -> 'Applied Materials, Inc.'"""
    if not asset:
        return asset
    n = re.split(r" - |\s+(?:Class [A-Z] )?(?:New )?(?:Common Stock|Common Shares|Ordinary Shares|American Depositary)",
                 asset)[0].strip().rstrip(",")
    return n or asset


def _row(r: dict) -> dict:
    return {
        "owner": OWNER_DE.get(r.get("owner_name"), r.get("owner_name")), "asset": _short(r.get("asset")),
        "ticker": r.get("ticker"), "asset_type": ASSET_DE.get(r.get("asset_type"), r.get("asset_type")),
        "type": r.get("type"), "type_de": TYPE_DE.get(r.get("type"), r.get("type_name")),
        "date": r.get("date"), "amount": r.get("amount"), "amount_low": r.get("amount_low"),
        "amount_high": r.get("amount_high"), "days_to_disclose": r.get("days_to_disclose"),
        "late": r.get("late"), "option": r.get("option"), "shares": r.get("shares"),
        "description": (r.get("description") or "")[:240] or None,
    }


def amount_de(row: dict) -> str:
    """'$1,000,001 - $5,000,000' -> '1–5 Mio. $'."""
    lo, hi = row.get("amount_low"), row.get("amount_high")

    def k(x):
        x = x - 1 if x % 1000 == 1 else x
        txt = f"{x / 1e6:g} Mio." if x >= 1e6 else f"{x / 1e3:g} Tsd."
        return txt.replace(".", ",", txt.count(".") - 1) if txt.count(".") > 1 else txt
    if lo and hi:
        return f"{k(lo)} – {k(hi)} $"
    if lo:
        return f"über {k(lo)} $"
    return row.get("amount") or "?"


def is_focus(last_name: str) -> bool:
    focus = {m.split()[-1].lower() for m in config.CONGRESS_FOCUS if m.strip()}
    return bool(last_name) and last_name.strip().lower() in focus


def _aggregate(items: list[dict], today: date) -> list[dict]:
    """Meistgehandelte Ticker der letzten 30 Tage (nach Meldedatum)."""
    since = (today - timedelta(days=30)).isoformat()
    agg: dict[str, dict] = {}
    for f in items:
        if (f.get("filed") or "") < since:
            continue
        for r in f.get("rows", []):
            t = r.get("ticker")
            if not t:
                continue
            a = agg.setdefault(t, {"ticker": t, "asset": r.get("asset"), "kaeufe": 0, "verkaeufe": 0, "members": []})
            if r["type"] == "P":
                a["kaeufe"] += 1
            elif r["type"] in ("S", "S (partial)"):
                a["verkaeufe"] += 1
            if f["name"] not in a["members"]:
                a["members"].append(f["name"])
    return sorted(agg.values(), key=lambda a: (-(a["kaeufe"] + a["verkaeufe"]), -len(a["members"]), a["ticker"]))[:25]


def run(net=None, now=None, push: bool = True) -> dict:
    net = net or Net()
    now = now or datetime.now().astimezone()
    today = now.date()
    rows = net.index(today.year)
    if today.month == 1:
        try:
            rows += net.index(today.year - 1)
        except P.PtrError:
            pass
    ptrs = P.select(rows, None, "P")

    state = store.load("state", "congress", {"seen": [], "last_check": None}) or {"seen": [], "last_check": None}
    first_run = state.get("last_check") is None
    fresh = P.new_since(ptrs, state, today, config.CONGRESS_FIRST_RUN_DAYS)
    fresh.sort(key=lambda r: (r["filed"] or "", r["doc_id"]), reverse=True)
    todo, later = fresh[: config.CONGRESS_MAX_READ], fresh[config.CONGRESS_MAX_READ:]

    pub = store.load("public", "congress", {}) or {}
    items = {f["doc_id"]: f for f in pub.get("filings", [])}
    new_items, errors = [], []
    with tempfile.TemporaryDirectory() as folder:
        for r in todo:
            item = {"doc_id": r["doc_id"], "name": r["name"], "last": r["last"], "district": r["district"],
                    "filed": r["filed"], "url": r["url"], "readable": False, "rows": [],
                    "focus": is_focus(r["last"])}
            try:
                rep = net.read_ptr(r["doc_id"], r["year"], r["filed"], folder)
            except (P.PtrError, OSError) as exc:
                errors.append(f"{r['doc_id']}: {exc}")
                later.append(r)              # beim nächsten Lauf erneut versuchen
                continue
            if rep is not None:
                item["readable"] = bool(rep["rows"])
                item["rows"] = [_row(x) for x in rep["rows"]]
            items[r["doc_id"]] = item
            new_items.append(item)

    keep_from = (today - timedelta(days=config.CONGRESS_KEEP_DAYS)).isoformat()
    filings = sorted((f for f in items.values() if (f.get("filed") or "") >= keep_from),
                     key=lambda f: (f.get("filed") or "", f["doc_id"]), reverse=True)
    store.save("public", "congress", {
        "updated": now.isoformat(), "filings": filings, "top": _aggregate(filings, today),
        "quelle": "disclosures-clerk.house.gov", "hinweis": HINWEIS,
        "fokus": config.CONGRESS_FOCUS, "senat": "Senatsmeldungen sind nicht enthalten (eigenes Portal mit Zustimmungspflicht)."})

    retry = {r["doc_id"] for r in later}
    state["seen"] = sorted(set(state.get("seen", [])) | ({r["doc_id"] for r in ptrs} - retry))
    state["last_check"] = now.isoformat()
    store.save("state", "congress", state)

    pushed = False
    trades = [f for f in new_items if f["rows"]]
    if push and trades and not first_run:
        pushed = digest_push(trades)
    s = store.load("public", "status", {}) or {}
    s.update({"version": VERSION, "congress_last": now.isoformat(), "congress_new": len(new_items),
              "congress_open": len(later), "congress_errors": errors[:5], "congress_filings": len(filings),
              "ok": True})
    store.save("public", "status", s)
    print(f"[kongress] {len(ptrs)} PTRs im Index, {len(new_items)} neu gelesen, {len(later)} offen")
    return {"new": len(new_items), "open": len(later), "pushed": pushed, "first_run": first_run}


def digest_push(trades: list[dict]) -> bool:
    n_rows = sum(len(f["rows"]) for f in trades)
    focus = [f for f in trades if f.get("focus")]
    lines = []
    for f in sorted(trades, key=lambda f: (not f.get("focus"), f["filed"] or ""))[:6]:
        r = f["rows"][0]
        what = r.get("ticker") or (r.get("asset") or "")[:28]
        more = f" (+{len(f['rows']) - 1} weitere)" if len(f["rows"]) > 1 else ""
        lines.append(f"• {f['last']} ({f['district']}): {r['type_de']} {what}, {amount_de(r)}{more}")
    if len(trades) > 6:
        lines.append(f"… und {len(trades) - 6} weitere Meldungen in der App")
    title = (f"🏛️ {focus[0]['last']} meldet Aktiengeschäfte" if focus
             else f"🏛️ Kongress: {n_rows} neue Aktiengeschäfte")
    url = config.app_url()
    return notify.send(title, "\n".join(lines), priority=4 if focus else 3, tags=["classical_building"],
                       click=(url + "#/kongress") if url else None)
