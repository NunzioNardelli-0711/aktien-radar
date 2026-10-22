"""Zwischenstände des Datenspeichers veröffentlichen.

Lange Läufe (die Daytrading-Schleife) sollen ihre Ergebnisse nicht erst am Ende
hochladen, sondern nach jedem Takt. .github/scripts/with-store.sh setzt dafür
RADAR_PUBLISH=1 und STORE_BRANCH; lokal und in Tests passiert hier nichts.
Der Branch bleibt wie beim Radar ein einziger Commit (amend + force push).
"""
import os
import subprocess
import time
from datetime import datetime, timezone

from . import config


def _git(*args, check=True):
    return subprocess.run(["git", "-C", str(config.STORE), *args], capture_output=True, text=True,
                          check=check, timeout=120)


def publish(label: str) -> bool:
    if os.environ.get("RADAR_PUBLISH") != "1":
        return False
    branch = os.environ.get("STORE_BRANCH", "data")
    try:
        _git("add", "-A")
        if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return True
        msg = f"Daten {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} ({label})"
        has_head = _git("rev-parse", "-q", "--verify", "HEAD", check=False).returncode == 0
        _git("commit", "-q", *(["--amend"] if has_head else []), "-m", msg)
        for attempt in range(3):
            if _git("push", "-q", "--force", "origin", f"HEAD:{branch}", check=False).returncode == 0:
                return True
            time.sleep(5 * (attempt + 1))
        print("[gitstore] Push fehlgeschlagen")
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[gitstore] {exc}")
    return False
