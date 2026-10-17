"""Push-Nachrichten über ntfy (iPhone-App "ntfy", kostenlos).

Priorität 5 = "urgent": erscheint sofort auf dem Sperrbildschirm, auf iOS als
zeitkritische Mitteilung (durchbricht den Fokus-Modus, wenn erlaubt)."""
import time

import requests

from . import config


def send(title: str, message: str, priority: int = 5, tags: list[str] | None = None,
         click: str | None = None) -> bool:
    payload = {"topic": config.NTFY_TOPIC, "title": title, "message": message,
               "priority": priority, "tags": tags or []}
    if click:
        payload["click"] = click
    if not config.NTFY_TOPIC:
        print(f"[notify] (Testmodus, kein NTFY_TOPIC) {title} | {message}")
        return False
    for attempt in range(3):
        try:
            r = requests.post(config.NTFY_SERVER, json=payload, timeout=15)
            if r.ok:
                return True
            print(f"[notify] HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as exc:
            print(f"[notify] Fehler: {exc}")
        time.sleep(2 * (attempt + 1))
    return False


def alert_push(a: dict) -> bool:
    title = f"🚀 {a['symbol'].replace('.DE', '')} {a['change_pct']:+.1f} % · {a['ampel']['emoji']} {a['score']}/100"
    msg = (f"{a['name']} – {a['ampel']['label']}\n"
           f"Grund: {a['grund']['label']}\n"
           f"Volumen {a['rel_vol']:.1f}× · Kurs {a['price']:.2f}\n"
           "Tippen für die Analyse")
    url = config.app_url()
    return send(title, msg, priority=5, tags=["chart_with_upwards_trend"],
                click=f"{url}#/a/{a['id']}" if url else None)
