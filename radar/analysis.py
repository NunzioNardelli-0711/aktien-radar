"""Fundierte Analyse einer auffälligen Aktie: Grund des Anstiegs, Fundamentaldaten
mit Branchenvergleich, technische Lage, Bewertung je Anlagehorizont und Ampel.

Die Bewertung ist regelbasiert und nachvollziehbar: jede Regel, die greift,
erscheint als Chance oder Risiko in der Begründung."""
import re
from datetime import datetime, timedelta, timezone

from . import config
from .fundamentals import extract
from .indicators import rsi, safe

DISCLAIMER = ("Automatisch erstellte, regelbasierte Einschätzung auf Basis öffentlicher, ggf. "
              "verzögerter Daten. Keine Anlageberatung und keine Kaufempfehlung – die Entscheidung "
              "und das Risiko liegen bei dir.")

REASONS = [
    ("takeover", "Übernahme / Fusion",
     r"acquir|takeover|buyout|merger|tender offer|to be bought|bid for|übernahme|fusion|kaufangebot"),
    ("earnings", "Quartalszahlen / Prognose",
     r"earnings|results|quarter|\bq[1-4]\b|revenue|guidance|outlook|beats|profit|quartal|zahlen|prognose|umsatz|gewinn"),
    ("approval", "Zulassung / Studiendaten",
     r"\bfda\b|approval|approved|trial|phase [1-3i]|zulassung|studie"),
    ("analyst", "Analysten-Hochstufung",
     r"upgrade|price target|raises target|outperform|overweight|kursziel|hochgestuft|kaufempfehlung"),
    ("contract", "Großauftrag / Partnerschaft",
     r"contract|\borders?\b|partnership|agreement|collaborat|\bdeal\b|auftrag|partnerschaft|kooperation"),
    ("capital", "Aktienrückkauf / Dividende",
     r"buyback|repurchase|dividend|rückkauf|dividende"),
    ("squeeze", "Spekulation / Short Squeeze",
     r"short squeeze|meme|retail traders|short sellers"),
]


def classify_reason(news: list[dict], now: datetime) -> dict:
    recent = []
    for n in news:
        try:
            t = datetime.fromisoformat(n["time"]) if n.get("time") else None
        except ValueError:
            t = None
        if t is None or now - t <= timedelta(days=3):
            recent.append(n)
    for key, label, pattern in REASONS:
        for n in recent:
            if re.search(pattern, n["title"], re.IGNORECASE):
                return {"key": key, "label": label, "headline": n["title"], "source": n.get("publisher", "")}
    return {"key": "none", "label": "Kein eindeutiger Grund in den Nachrichten gefunden",
            "headline": recent[0]["title"] if recent else None,
            "source": recent[0].get("publisher", "") if recent else ""}


def _clamp(x: float) -> int:
    return int(max(0, min(100, round(x))))


def _ampel(score: int) -> dict:
    if score >= config.AMPEL_GREEN:
        return {"farbe": "gruen", "label": "interessant", "emoji": "🟢"}
    if score >= config.AMPEL_YELLOW:
        return {"farbe": "gelb", "label": "beobachten", "emoji": "🟡"}
    return {"farbe": "rot", "label": "Finger weg", "emoji": "🔴"}


def _horizon_label(score: int) -> str:
    return "chancenreich" if score >= config.AMPEL_GREEN else ("neutral" if score >= config.AMPEL_YELLOW else "ungünstig")


def _pct(x, digits=1):
    return None if x is None else f"{x * 100:+.{digits}f} %"


def score(q: dict, b: dict, f: dict, med: dict, reason_key: str, earnings_days: int | None):
    """Liefert (short, mid, long, chancen, risiken). Jede Regel hinterlässt eine Notiz."""
    chancen, risiken = [], []
    price, chg, rv = q["price"], q["change_pct"], q["rel_vol"]
    rsi_now = q.get("rsi_now")

    # ---- Kurzfristig: Kraft und Nachhaltigkeit des Impulses --------------
    s = 50
    if rv >= 5:
        s += 12; chancen.append(f"Sehr hohes Handelsvolumen ({rv:.1f}× normal) – breites Interesse")
    elif rv >= 3:
        s += 8; chancen.append(f"Deutlich erhöhtes Volumen ({rv:.1f}× normal)")
    else:
        s += 4
    if reason_key == "none":
        s -= 12; risiken.append("Kein klarer Nachrichtenauslöser – Anstieg könnte spekulativ sein")
    else:
        s += 10
    if reason_key in ("earnings", "approval", "contract"):
        s += 5; chancen.append("Fundamentaler Auslöser – solche Anstiege halten öfter als reine Stimmungssprünge")
    if reason_key == "takeover":
        s -= 15; risiken.append("Übernahmefantasie: weiterer Anstieg meist durch den Angebotspreis begrenzt")
    if reason_key == "squeeze":
        s -= 10; risiken.append("Spekulativer Short Squeeze – starke Rückschläge typisch")
    if rsi_now is not None:
        if rsi_now > 85:
            s -= 15; risiken.append(f"Stark überkauft (RSI {rsi_now:.0f}) – Gewinnmitnahmen wahrscheinlich")
        elif rsi_now > 75:
            s -= 8; risiken.append(f"Überkauft (RSI {rsi_now:.0f})")
        else:
            s += 3
    if chg > 30:
        s -= 12; risiken.append(f"Extremer Tagessprung (+{chg:.0f} %) – hohes Rücksetzer-Risiko")
    elif chg > 20:
        s -= 6; risiken.append(f"Sehr großer Tagessprung (+{chg:.0f} %)")
    if b.get("high52") and price > b["high52"]:
        s += 6; chancen.append("Neues 52-Wochen-Hoch – kein Widerstand durch frühere Höchststände")
    if earnings_days is not None and 0 <= earnings_days <= 7:
        risiken.append(f"Quartalszahlen in {earnings_days} Tag(en) – erhöhte Schwankung möglich")
    short = _clamp(s)

    # ---- Mittelfristig: Trend und Wachstum -------------------------------
    m = 50
    sma50, sma200 = b.get("sma50"), b.get("sma200")
    if sma50 and price > sma50:
        m += 8
    if sma50 and sma200:
        if sma50 > sma200:
            m += 10; chancen.append("Intakter Aufwärtstrend (50-Tage-Linie über 200-Tage-Linie)")
        elif price < sma200:
            m -= 10; risiken.append("Langfristiger Abwärtstrend – Kurs trotz Sprung unter der 200-Tage-Linie")
    rg, eg = f.get("rev_growth"), f.get("eps_growth")
    if rg is not None:
        if rg > 0.15:
            m += 12; chancen.append(f"Starkes Umsatzwachstum ({_pct(rg, 0)})")
        elif rg > 0.05:
            m += 6
        elif rg < 0:
            m -= 10; risiken.append(f"Umsatz schrumpft ({_pct(rg, 0)})")
    if eg is not None:
        if eg > 0.15:
            m += 8; chancen.append(f"Gewinn wächst stark ({_pct(eg, 0)})")
        elif eg < 0:
            m -= 8; risiken.append(f"Gewinn rückläufig ({_pct(eg, 0)})")
    if reason_key == "earnings":
        m += 6
    if reason_key == "takeover":
        m -= 10
    mid = _clamp(m)

    # ---- Langfristig: Bewertung und Qualität -----------------------------
    l = 50
    pe, med_pe = f.get("pe"), (med or {}).get("pe")
    if pe is None or pe <= 0:
        if f.get("margin") is not None and f["margin"] < 0:
            l -= 12; risiken.append("Unternehmen schreibt Verluste")
    elif med_pe:
        ratio = pe / med_pe
        if ratio < 0.8:
            l += 12; chancen.append(f"Günstig bewertet: KGV {pe:.0f} vs. Branche {med_pe:.0f}")
        elif ratio < 1.2:
            l += 4
        elif ratio < 2:
            l -= 6; risiken.append(f"Teurer als die Branche: KGV {pe:.0f} vs. {med_pe:.0f}")
        else:
            l -= 14; risiken.append(f"Sehr hoch bewertet: KGV {pe:.0f} vs. Branche {med_pe:.0f}")
    else:
        l += 8 if pe < 15 else (0 if pe < 30 else -8)
    mg = f.get("margin")
    if mg is not None:
        if mg > 0.15:
            l += 10; chancen.append(f"Hohe Gewinnmarge ({mg * 100:.0f} %)")
        elif mg > 0.05:
            l += 4
        elif mg < 0:
            l -= 10
    de = f.get("de")
    if de is not None:
        if de < 50:
            l += 10; chancen.append("Geringe Verschuldung")
        elif de < 100:
            l += 4
        elif de > 200:
            l -= 12; risiken.append(f"Hohe Verschuldung (Verschuldungsgrad {de / 100:.1f}×)")
    if rg is not None and rg > 0.10:
        l += 6
    long_ = _clamp(l)
    return short, mid, long_, chancen, risiken


def analyze(sym: str, meta: dict, b: dict, q: dict, fund_cache: dict, provider, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    info = provider.info(sym)
    f = extract(info) if info else fund_cache.get("items", {}).get(sym, {})
    sector = f.get("sector") or meta.get("sector", "")
    med = fund_cache.get("sector_medians", {}).get(sector, {})
    news = provider.news(sym)
    reason = classify_reason(news, now)
    ed = provider.next_earnings(sym)
    earnings_days = (ed - now.date()).days if ed else None

    q = dict(q)
    q["rsi_now"] = rsi([c for c in b.get("closes", []) if c is not None] + [q["price"]])
    short, mid, long_, chancen, risiken = score(q, b, f, med, reason["key"], earnings_days)

    total = round(0.35 * short + 0.35 * mid + 0.30 * long_)
    if reason["key"] == "takeover":
        total = min(total, 55)
    if not f or all(f.get(k) is None for k in ("pe", "rev_growth", "margin", "de")):
        risiken.append("Fundamentaldaten unvollständig – Einschätzung weniger belastbar")
    total = _clamp(total)
    ampel = _ampel(total)
    name = f.get("name") or meta.get("name") or sym

    saetze = [f"{name} steigt um {q['change_pct']:+.1f} % bei {q['rel_vol']:.1f}-fachem Handelsvolumen."]
    if reason["key"] != "none":
        saetze.append(f"Wahrscheinlicher Auslöser: {reason['label']}"
                      + (f" („{reason['headline']}“)." if reason.get("headline") else "."))
    else:
        saetze.append("In den aktuellen Nachrichten findet sich kein klarer Auslöser.")
    if chancen:
        saetze.append(f"Pro: {chancen[0]}.")
    if risiken:
        saetze.append(f"Contra: {risiken[0]}.")
    saetze.append({
        "gruen": "Gesamtbild: interessant – eine nähere Prüfung lohnt sich.",
        "gelb": "Gesamtbild: gemischt – beobachten statt überstürzt handeln.",
        "rot": "Gesamtbild: die Risiken überwiegen – eher Finger weg.",
    }[ampel["farbe"]])

    price = q["price"]
    technik = {
        "kurs": safe(price, 2), "vortag": b.get("prev_close"),
        "rsi": safe(q["rsi_now"], 1), "sma50": b.get("sma50"), "sma200": b.get("sma200"),
        "ueber_sma50": bool(b.get("sma50") and price > b["sma50"]),
        "ueber_sma200": bool(b.get("sma200") and price > b["sma200"]),
        "high52": b.get("high52"), "low52": b.get("low52"),
        "abstand_high52_pct": safe((price / b["high52"] - 1) * 100, 1) if b.get("high52") else None,
        "rel_volumen": safe(q["rel_vol"], 2), "volumen": q.get("volume"),
        "avg_volumen20": b.get("avg_vol20"),
        "trend": ("Aufwärtstrend" if b.get("sma50") and b.get("sma200") and b["sma50"] > b["sma200"]
                  else "Abwärtstrend" if b.get("sma50") and b.get("sma200") else "unklar"),
    }
    fundamental = {
        "kgv": f.get("pe"), "kgv_erwartet": f.get("fpe"), "umsatzwachstum": f.get("rev_growth"),
        "gewinnwachstum": f.get("eps_growth"), "marge": f.get("margin"), "verschuldung": f.get("de"),
        "marktkap": f.get("mcap"), "kursziel_analysten": f.get("target"), "analysten": f.get("rec"),
        "sektor": sector, "branche": f.get("industry", ""), "waehrung": f.get("currency", ""),
        "beschreibung": f.get("summary", ""),
        "branche_median": {"kgv": med.get("pe"), "umsatzwachstum": med.get("rev_growth"),
                           "marge": med.get("margin"), "verschuldung": med.get("de"), "n": med.get("n")},
    }
    return {
        "id": f"{now.strftime('%Y%m%d')}-{sym}",
        "symbol": sym, "name": name, "market": meta.get("market"), "indices": meta.get("indices", []),
        "time": now.isoformat(), "price": safe(price, 2), "change_pct": safe(q["change_pct"], 2),
        "rel_vol": safe(q["rel_vol"], 2),
        "score": total, "ampel": ampel,
        "horizonte": {
            "kurzfristig": {"score": short, "label": _horizon_label(short), "zeitraum": "Tage"},
            "mittelfristig": {"score": mid, "label": _horizon_label(mid), "zeitraum": "Wochen bis Monate"},
            "langfristig": {"score": long_, "label": _horizon_label(long_), "zeitraum": "Jahre"},
        },
        "grund": reason, "begruendung": " ".join(saetze[:5]),
        "chancen": chancen, "risiken": risiken,
        "fundamental": fundamental, "technik": technik,
        "naechste_zahlen": str(ed) if ed else None,
        "news": news[:6], "disclaimer": DISCLAIMER,
    }
