"""Handelszeiten von Xetra und US-Börsen (ohne Feiertagskalender:
an Feiertagen liefert die Datenquelle keinen Tageskurs, der Scan überspringt dann)."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

MARKETS = {
    "DE": {"tz": "Europe/Berlin", "open": time(9, 0), "close": time(17, 30),
           "index": "^GDAXI", "label": "Xetra", "currency": "EUR"},
    "US": {"tz": "America/New_York", "open": time(9, 30), "close": time(16, 0),
           "index": "^GSPC", "label": "NYSE/Nasdaq", "currency": "USD"},
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_now(market: str, now: datetime | None = None) -> datetime:
    return (now or utcnow()).astimezone(ZoneInfo(MARKETS[market]["tz"]))


def local_today(market: str, now: datetime | None = None):
    return local_now(market, now).date()


def is_open(market: str, now: datetime | None = None) -> bool:
    loc = local_now(market, now)
    m = MARKETS[market]
    return loc.weekday() < 5 and m["open"] <= loc.time() < m["close"]


def is_closed_for_day(market: str, now: datetime | None = None) -> bool:
    """True, wenn der heutige Handel beendet ist (oder Wochenende)."""
    loc = local_now(market, now)
    return loc.weekday() >= 5 or loc.time() >= MARKETS[market]["close"]


def session_fraction(market: str, now: datetime | None = None) -> float:
    """Anteil der bereits verstrichenen Handelszeit (0..1)."""
    loc = local_now(market, now)
    m = MARKETS[market]
    start = loc.replace(hour=m["open"].hour, minute=m["open"].minute, second=0, microsecond=0)
    end = loc.replace(hour=m["close"].hour, minute=m["close"].minute, second=0, microsecond=0)
    frac = (loc - start).total_seconds() / (end - start).total_seconds()
    return max(0.0, min(1.0, frac))


def open_markets(now: datetime | None = None) -> list[str]:
    return [m for m in MARKETS if is_open(m, now)]
