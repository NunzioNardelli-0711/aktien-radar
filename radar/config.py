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

# --- Daytrading (nur US-Börsen; Werkzeuge aus day-trader-skill) -------------
# Läuft im eigenen Workflow "Daytrading" und speichert in den Branch "daytrade".
DT_UNIVERSE_MAX_AGE_DAYS = 7      # Nasdaq-Trader-Liste (~5.900 US-Aktien) wöchentlich neu
DT_DAILY_MIN_PRICE = 5.0          # Setup-Scanner: Mindestkurs in USD ...
DT_DAILY_MIN_VOLUME = 1_000_000   # ... und Mindest-Tagesvolumen (Stück)
DT_ORB_MINUTES = 15               # Eröffnungsspanne 9:30–9:45 New York
DT_ORB_MIN_PRICE = 5.0
DT_ORB_MIN_PREV_VOLUME = 1_000_000  # ORB-Scan nur für liquide Werte (Vortagesvolumen)
DT_ORB_MAX_CONFIRM = 150          # höchstens so viele Detail-Charts je ORB-Scan
DT_ORB_EVERY_EARLY = 10           # ORB-Scan alle 10 Min. bis 11:00 New York ...
DT_ORB_EVERY_LATE = 30            # ... danach alle 30 Min.
DT_NO_ENTRIES_BEFORE = "09:45"    # Einstiegs-Fenster (New Yorker Zeit)
DT_NO_ENTRIES_AFTER = "15:30"
DT_ENTRY_WATCH_MAX = 25           # so viele Setups beobachtet der Entry-Timer Kerze für Kerze
DT_SETUP_PRIORITY = ["breakout_20d", "bull_flag", "oversold_bounce", "reclaim_ma20", "oversold"]
DT_TARGET_R = 1.0                 # Kursziel = Einstieg + 1 × Risiko (Stop = Mitte der Spanne)
DT_FLAT_BY = "15:55"              # Time Machine: Position spätestens hier glattstellen
DT_TM_REPLAYS = 10_000
DT_TM_SEED = 19
DT_TM_ORB_TOP = 5                 # Time Machine zusätzlich für die 5 umsatzstärksten ORB-Treffer
DT_MAX_ENTRY_PUSHES = 10          # Obergrenze Einstiegs-Pushes pro Tag
DT_CYCLE_MINUTES = 5              # Takt der Daytrading-Schleife
DT_PAUSE = 0.3                    # Pause zwischen Abrufen (Yahoo schonen)
DT_MAX_CYCLE_ERRORS = 6           # so viele Fehler in Folge, dann bricht der Lauf ab

# --- Kongress-Aktiengeschäfte (US-Repräsentantenhaus, STOCK Act) ------------
CONGRESS_FOCUS = ["Pelosi"]       # Meldungen dieser Abgeordneten mit höherer Push-Priorität
CONGRESS_KEEP_DAYS = 60           # so lange bleiben Meldungen in der App
CONGRESS_FIRST_RUN_DAYS = 30      # beim ersten Lauf: Meldungen der letzten 30 Tage nachladen
CONGRESS_MAX_READ = 60            # höchstens so viele PDFs pro Lauf lesen

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
