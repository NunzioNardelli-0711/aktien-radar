# Aktien-Radar

Überwacht DAX, MDAX, SDAX, TecDAX, S&P 500 und Nasdaq 100 alle 5 Minuten während der
Handelszeiten. Steigt eine Aktie am Tag um **≥ 10 %** bei **≥ 2-fachem Handelsvolumen**,
kommt sofort eine **Push-Nachricht auf den iPhone-Sperrbildschirm**, mit Ampel-Bewertung
und Link zur ausführlichen Analyse.

> Entscheidungshilfe, keine Anlageberatung. Die Bewertung ist regelbasiert und arbeitet mit
> kostenlosen, bis zu ~15 Minuten verzögerten Daten.

## Was passiert automatisch

| Wann | Was |
|---|---|
| Alle 5 Min. (Mo–Fr, Börsenzeiten) | Scan aller Werte, Analyse von Treffern, Push-Alarm |
| Mo–Fr vor Börsenstart | Basisdaten (Trends, RSI, Durchschnittsvolumen), Frühwarn-Watchlist mit Push-Zusammenfassung |
| Samstags | Indexlisten und Fundamentaldaten (KGV, Wachstum, Marge, Verschuldung, Branchen-Mediane) |
| 2× täglich | Selbstprüfung; bei Problemen Push „Wartung nötig“ |
| Bei Fehlern | Push „Fehler“ (höchstens alle 3 Std.) und E-Mail von GitHub |

GitHub führt geplante Läufe bei hoher Last manchmal ein paar Minuten verspätet aus.

## Einrichtung (einmalig, ca. 15 Minuten)

### 1. iPhone: ntfy installieren
1. App **ntfy** aus dem App Store installieren (kostenlos).
2. In ntfy auf **+** tippen und das Thema eintragen: `aktienradar-oepnsfk0fumn6i`.
   Server bleibt `ntfy.sh`. Das Thema ist dein privater Kanal, gib es nicht weiter.
3. Mitteilungen erlauben. Unter *Einstellungen → Mitteilungen → ntfy*: Sperrbildschirm,
   Banner und **Zeitkritische Mitteilungen** einschalten.
4. Bei Fokus-Modi (z. B. „Nicht stören“) ntfy unter *Erlaubte Apps* hinzufügen,
   wenn du Alarme auch dann sehen willst.

### 2. GitHub-Repository
1. Kostenloses Konto auf github.com anlegen, falls noch keins vorhanden ist.
2. Neues Repository **`aktien-radar`** anlegen, Sichtbarkeit **Public**.
   Nur öffentliche Repos haben unbegrenzte kostenlose Laufzeit, die der 5-Minuten-Scan braucht.
   Dein ntfy-Thema bleibt trotzdem geheim (siehe Schritt 3).
3. *Settings → Secrets and variables → Actions → New repository secret*:
   Name `NTFY_TOPIC`, Wert `aktienradar-oepnsfk0fumn6i`.
4. Code hochladen. Am einfachsten sagst du Claude den Repo-Namen, Claude schiebt dann alles
   hoch. Alternativ geht es mit GitHub Desktop.
5. *Settings → Pages*: Source **Deploy from a branch**, Branch `main`, Ordner `/docs`.
6. *Actions*: Workflows aktivieren, falls GitHub danach fragt.

### 3. Starten und testen
1. *Actions → Test-Alarm senden → Run workflow*: Auf dem iPhone muss eine Push-Nachricht ankommen.
2. *Actions → Wochenlauf → Run workflow* (dauert 10–20 Min.), danach *Tageslauf → Run workflow*.
3. Web-App öffnen: **https://nunzionardelli-0711.github.io/aktien-radar/**.
   - iPhone: in Safari öffnen → Teilen → **Zum Home-Bildschirm**.
   - PC: im Browser öffnen; Chrome/Edge bieten „Installieren“ an.

## Daytrading (nur US-Börsen)

Aufgebaut auf vier Werkzeugen aus [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, unverändert in `radar/vendor/daytrader/`). Workflow **Daytrading**, Daten im Branch `daytrade`.

| Baustein | Was er tut |
|---|---|
| **Setup-Scanner** | Vor Börsenstart: alle ~5.900 US-Aktien (Nasdaq-Trader-Liste) nach 20-Tage-Ausbruch, Bullenflagge, Rückeroberung der 20-Tage-Linie, überverkauft und Erholung aus überverkauft. Ab 9:50 New York zusätzlich Opening-Range-Breakouts im liquiden Teil. |
| **Entry-Timer** | Beobachtet die 25 besten Setups (plus `config/daytrade_watch.txt`) alle 5 Minuten Kerze für Kerze und meldet die erste 5-Min.-Kerze, die über dem Hoch der ersten 15 Minuten schließt (9:45–15:30 New York). |
| **Time Machine** | Spielt jeden Einstieg 10.000-mal mit den 5-Min.-Kerzen der letzten ~60 Tage durch (Stop = Mitte der Spanne, mind. 0,4 %; Ziel 1R; glatt bis 15:55) und zeigt, wie oft dieselbe Regel früher Ziel oder Stop erreicht hat. |

Push 🎯 nur, wenn die Time Machine zum Ziel tendiert, das Signal frisch ist (≤ 15 Min.) und höchstens
10 pro Tag – Werte aus der eigenen Liste immer. Alles andere steht in der App unter **Daytrade**.
Es wird nie eine Order platziert.

## Kongress-Aktiengeschäfte

Workflow **Kongress**, dreimal pro Werktag, Daten im Branch `congress`: liest neue Pflichtmeldungen (PTR)
von Abgeordneten des Repräsentantenhauses beim House Clerk, zeigt sie mit Kauf/Verkauf, Betragsspanne
und Meldeverzug und schickt einen Sammel-Push 🏛️ (höhere Priorität bei Pelosi, siehe `CONGRESS_FOCUS`).
Senatsmeldungen sind nicht enthalten.

## Bewertung

- **Kurzfristig (Tage):** Volumen, Nachrichtenauslöser, RSI/Überhitzung, Größe des Sprungs, 52-Wochen-Hoch
- **Mittelfristig (Wochen–Monate):** Trend (50/200-Tage-Linie), Umsatz- und Gewinnwachstum
- **Langfristig (Jahre):** KGV im Branchenvergleich, Gewinnmarge, Verschuldung
- **Gesamt:** 35 % kurz + 35 % mittel + 30 % lang. Ampel: 🟢 ab 65 · 🟡 45–64 · 🔴 unter 45.
  Bei Übernahmen liegt die Obergrenze bei 55, weil der Kurs dann meist am Angebotspreis klebt.

Die Schwellenwerte stehen in `radar/config.py`. Zusätzliche Aktien kommen in `config/extra_tickers.txt`.

## Technik

- `radar/`: Python-Code (Scanner, Analyse, Push)
- `docs/`: Web-App (PWA) für PC und iPhone; `docs/sample/` enthält Demo-Daten
- Branch `data`: Laufzeitdaten (`state/` intern, `public/` für die App), wird automatisch gepflegt
- `tests/test_offline.py`: kompletter Durchlauf mit synthetischen Daten, ohne Internet
- `tests/test_daytrade_offline.py`: Daytrading und Kongress mit echten gespeicherten Daten
- `tests/daytrader/`: Original-Tests der übernommenen Werkzeuge
- Branches `daytrade` und `congress`: Laufzeitdaten der neuen Module
- `python -m radar smoke` bzw. Workflow *Live-Rauchtest*: prüft alles gegen die echten Quellen, ohne Push
