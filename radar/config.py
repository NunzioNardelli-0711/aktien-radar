"""Zentrale Einstellungen des Aktien-Radars.

Alle Schwellenwerte stehen hier an einer Stelle, damit sie sich ohne
Suchen im restlichen Code anpassen lassen.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Der Datenspeicher liegt in einem eigenen Git-Branch ("data"), der im
# Workflow nach ./store ausgecheckt wird. state/ = intern, public/ = für die App.
STORE = Path(os.environ.get("RADAR_STORE", ROOT / "store"))
STATE = STORE / "state"
PUBLIC = STORE / "public"

# --- Alarm-Kriterien -------------------------------------------------------
MIN_CHANGE_PCT = 10.0          # Tagesanstieg ggü. Vortagesschluss in %
MIN_REL_VOLUME = 2.0           # Volumen mind. 2x des 20-Tage-Schnitts (hochgerechnet)
MIN_PRICE = 1.0                # Penny Stocks ausschließen (EUR/USD)
MIN_AVG_TURNOVER = 500_000     # Mindest-Tagesumsatz in EUR/USD (Liquidität)
REALERT_EXTRA_PCT = 5.0        # Erneuter Alarm am selben Tag erst bei +5 %-Punkten mehr
VOLUME_AVG_DAYS = 20
MIN_SESSION_FRACTION = 0.15    # Früh am Tag Volumen nicht auf winzige Basis hochrechnen

# --- Frühwarn-Watchlist ----------------------------------------------------
WATCHLIST_MAX = 25
WATCH_VOLUME_SPIKE = 2.0       # Volumen >= 2x Schnitt ...
WATCH_QUIET_MOVE_PCT = 3.0     # ... bei Kursbewegung < 3 % ("stille Akkumulation")
WATCH_RANGE_WIDTH = 0.10       # Seitwärtsphase: 20-Tage-Spanne < 10 %
WATCH_REL_STRENGTH = 10.0      # 20-Tage-Performance >= 10 %-Punkte über dem Index
WATCH_EARNINGS_DAYS = 7

# --- Bewertung -------------------------------------------------------------
AMPEL_GREEN = 65
AMPEL_YELLOW = 45

# --- Betrieb ---------------------------------------------------------------
BASELINE_MAX_AGE_HOURS = 20
UNIVERSE_MAX_AGE_DAYS = 7
FUNDAMENTALS_MAX_AGE_DAYS = 8
ERROR_PUSH_HOURS = 3
HISTORY_MAX = 300

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()


def app_url() -> str:
    """Adresse der Web-App (GitHub Pages), aus dem Repo-Namen abgeleitet."""
    explicit = os.environ.get("APP_URL", "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""
