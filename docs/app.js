/* Aktien-Radar – Web-App (PWA). Liest die Daten, die der Scanner im Branch
   "data" ablegt, direkt von raw.githubusercontent.com. */
(() => {
  "use strict";

  // ---- Datenquelle bestimmen ---------------------------------------------
  const params = new URLSearchParams(location.search);
  const DATA = (() => {
    if (params.get("data")) return params.get("data").replace(/\/?$/, "/");
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      const owner = host.split(".")[0];
      const repo = location.pathname.split("/").filter(Boolean)[0] || `${owner}.github.io`;
      return `https://raw.githubusercontent.com/${owner}/${repo}/data/public/`;
    }
    return "sample/"; // lokale Vorschau mit Beispieldaten
  })();
  const DEMO = DATA === "sample/";

  const $view = document.getElementById("view");
  const $pill = document.getElementById("statusPill");
  const cache = {};

  async function load(name, fresh = false) {
    if (!fresh && cache[name] && Date.now() - cache[name].t < 30000) return cache[name].d;
    const r = await fetch(`${DATA}${name}.json?t=${Math.floor(Date.now() / 60000)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    const d = await r.json();
    cache[name] = { d, t: Date.now() };
    return d;
  }
  const tryLoad = (name) => load(name).catch(() => null);

  // ---- Formatierung --------------------------------------------------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = (x, d = 2) => (x == null || isNaN(x) ? "–" : Number(x).toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const pct = (x, d = 1) => (x == null ? "–" : `${x > 0 ? "+" : ""}${nf(x, d)} %`);
  const frac = (x, d = 1) => (x == null ? "–" : pct(x * 100, d));
  const short = (s) => String(s).replace(/\.DE$/, "");
  const cur = (m) => (m === "DE" ? "€" : "$");
  const big = (x) => x == null ? "–" : x >= 1e12 ? `${nf(x / 1e12, 1)} Bio.` : x >= 1e9 ? `${nf(x / 1e9, 1)} Mrd.` : x >= 1e6 ? `${nf(x / 1e6, 1)} Mio.` : nf(x, 0);
  const time = (iso) => iso ? new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "–";
  const dateTime = (iso) => iso ? new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";
  const ago = (iso) => {
    if (!iso) return "nie";
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (m < 1) return "gerade eben";
    if (m < 60) return `vor ${m} Min.`;
    if (m < 60 * 36) return `vor ${Math.round(m / 60)} Std.`;
    return `vor ${Math.round(m / 1440)} Tagen`;
  };
  const AMPEL_TXT = { gruen: "interessant", gelb: "beobachten", rot: "Finger weg" };

  // ---- Bausteine -----------------------------------------------------------
  function alertCard(a) {
    const live = a.live || {};
    const chg = live.change_pct ?? a.change_pct;
    return `<a class="card" href="#/a/${encodeURIComponent(a.id)}">
      <div class="row">
        <div class="ampel ${a.ampel.farbe}" aria-label="${esc(a.ampel.label)}">${a.score}</div>
        <div class="grow">
          <div class="sym">${esc(short(a.symbol))} <span class="tag ${a.ampel.farbe}">${esc(a.ampel.label)}</span></div>
          <div class="name">${esc(a.name)}</div>
        </div>
        <div><div class="chg num ${chg >= 0 ? "up" : "down"}">${pct(chg)}</div>
          <div class="name num" style="text-align:right">${nf(live.price ?? a.price)} ${cur(a.market)}</div></div>
      </div>
      <div class="meta"><span>⏱ ${time(a.time)}</span><span>📊 Vol. ${nf(a.rel_vol, 1)}×</span><span>📰 ${esc(a.grund)}</span></div>
    </a>`;
  }

  const empty = (title, text) => `<div class="card empty"><b>${title}</b>${text}</div>`;

  // ---- Ansichten -----------------------------------------------------------
  async function home() {
    const [alerts, movers] = await Promise.all([tryLoad("alerts"), tryLoad("movers")]);
    const items = alerts?.items || [];
    let html = `<h1>Alarme heute</h1><p class="sub">Anstieg ≥ 10 % und Volumen ≥ 2× Durchschnitt · DAX, MDAX, SDAX, TecDAX, S&amp;P 500, Nasdaq 100</p>`;
    html += items.length ? items.map(alertCard).join("")
      : empty("Noch kein Alarm heute", "Sobald eine Aktie die Kriterien erfüllt, bekommst du sofort eine Push-Nachricht.");
    const mv = movers?.items || [];
    if (mv.length) {
      html += `<h2>Stärkste Bewegungen (letzter Scan, ${time(movers.updated)})</h2><div class="card"><table>
        <tr><th>Aktie</th><th class="r">Änderung</th><th class="r">Volumen</th></tr>
        ${mv.map((m) => `<tr><td><b>${esc(short(m.symbol))}</b> ${m.alarm ? "⚡" : ""}<br><span class="name">${esc(m.name)}</span></td>
          <td class="r num ${m.change_pct >= 0 ? "chg up" : "chg down"}" style="font-size:15px">${pct(m.change_pct)}</td>
          <td class="r num">${nf(m.rel_vol, 1)}×</td></tr>`).join("")}</table></div>`;
    }
    return html;
  }

  async function watch() {
    const wl = await tryLoad("watchlist");
    const items = wl?.items || [];
    let html = `<h1>Frühwarn-Watchlist</h1><p class="sub">Aktien mit typischen Vorzeichen für stärkere Bewegungen · aktualisiert ${dateTime(wl?.updated)}</p>`;
    html += `<p class="note">⚠️ ${esc(wl?.hinweis || "Hinweise, keine Prognose.")}</p>`;
    html += items.length ? items.map((w) => `<div class="card">
        <div class="row"><div class="grow"><div class="sym">${esc(short(w.symbol))}</div><div class="name">${esc(w.name)}</div></div>
        <div style="text-align:right"><div class="num"><b>${nf(w.price)} ${cur(w.market)}</b></div><div class="name num">Vortag ${pct(w.last_change_pct)}</div></div></div>
        <ul class="signals">${w.signals.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
        <div class="meta"><span>Signalstärke ${"●".repeat(Math.max(1, Math.min(5, Math.round(w.points / 2))))}</span>${w.rsi14 ? `<span>RSI ${nf(w.rsi14, 0)}</span>` : ""}</div>
      </div>`).join("") : empty("Watchlist leer", "Sie wird jeden Handelstag vor Börsenstart neu berechnet.");
    return html;
  }

  async function history() {
    const h = (await tryLoad("history")) || [];
    let html = `<h1>Verlauf</h1><p class="sub">Alle Alarme der letzten Zeit</p>`;
    if (!h.length) return html + empty("Noch keine Alarme", "Hier erscheinen alle bisherigen Alarme.");
    let day = "";
    for (const a of h) {
      const d = new Date(a.time).toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" });
      if (d !== day) { html += `<h2>${d}</h2>`; day = d; }
      html += alertCard(a);
    }
    return html;
  }

  async function detail(id) {
    const a = await load(`a/${id}`);
    const live = a.live || {};
    const f = a.fundamental || {}, t = a.technik || {}, bm = f.branche_median || {};
    const hz = Object.entries(a.horizonte).map(([k, v]) => {
      const col = v.score >= 65 ? "var(--green)" : v.score >= 45 ? "var(--yellow)" : "var(--red)";
      return `<div class="hz"><div class="l">${k[0].toUpperCase() + k.slice(1)}</div><div class="v num">${v.score}</div>
        <div class="l">${esc(v.label)} · ${esc(v.zeitraum)}</div><div class="bar"><i style="width:${v.score}%;background:${col}"></i></div></div>`;
    }).join("");
    const cmp = (label, val, med, fmt, better) => {
      let mark = "";
      if (val != null && med != null) mark = (better === "low" ? val < med : val > med) ? " ✅" : " ⚠️";
      return `<tr><td>${label}</td><td class="r num">${fmt(val)}${mark}</td><td class="r num">${fmt(med)}</td></tr>`;
    };
    const kgv = (x) => (x == null ? "–" : nf(x, 1));
    const de = (x) => (x == null ? "–" : `${nf(x / 100, 2)}×`);
    return `<a class="back" href="#/">‹ Alle Alarme</a>
      <div class="card"><div class="hero">
        <div class="ampel ${a.ampel.farbe}">${a.score}</div>
        <div class="grow"><div class="sym" style="font-size:20px">${esc(short(a.symbol))} <span class="tag ${a.ampel.farbe}">${a.ampel.emoji} ${esc(a.ampel.label)}</span></div>
          <div class="name">${esc(a.name)} · ${esc((a.indices || []).join(", "))}</div></div>
      </div>
      <div class="row" style="margin-top:14px;align-items:baseline">
        <div class="big num">${nf(live.price ?? a.price)} ${cur(a.market)}</div>
        <div class="chg num ${(live.change_pct ?? a.change_pct) >= 0 ? "up" : "down"}">${pct(live.change_pct ?? a.change_pct)}</div>
      </div>
      <div class="meta"><span>Alarm ${dateTime(a.time)} bei ${pct(a.change_pct)}</span>${live.time ? `<span>Stand ${time(live.time)}</span>` : ""}<span>Volumen ${nf(a.rel_vol, 1)}×</span></div>
      </div>

      <h2>Einschätzung</h2>
      <div class="card"><p style="margin:0">${esc(a.begruendung)}</p></div>
      <div class="horizons">${hz}</div>

      <h2>Grund des Anstiegs</h2>
      <div class="card"><b>${esc(a.grund.label)}</b>${a.grund.headline ? `<p class="sub" style="margin-top:6px">„${esc(a.grund.headline)}“ ${a.grund.source ? `– ${esc(a.grund.source)}` : ""}</p>` : ""}
        ${a.naechste_zahlen ? `<p class="note">Nächste Quartalszahlen: ${new Date(a.naechste_zahlen).toLocaleDateString("de-DE")}</p>` : ""}</div>

      <h2>Chancen</h2>
      <div class="card">${a.chancen.length ? `<ul class="pc pro">${a.chancen.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : `<span class="note">Keine besonderen Stärken erkannt.</span>`}</div>
      <h2>Risiken</h2>
      <div class="card">${a.risiken.length ? `<ul class="pc con">${a.risiken.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : `<span class="note">Keine besonderen Risiken erkannt.</span>`}</div>

      <h2>Fundamentaldaten & Branchenvergleich</h2>
      <div class="card"><table>
        <tr><th>Kennzahl</th><th class="r">Aktie</th><th class="r">Branche (Median)</th></tr>
        ${cmp("KGV", f.kgv, bm.kgv, kgv, "low")}
        ${cmp("Umsatzwachstum", f.umsatzwachstum, bm.umsatzwachstum, frac, "high")}
        ${cmp("Gewinnmarge", f.marge, bm.marge, frac, "high")}
        ${cmp("Verschuldungsgrad", f.verschuldung, bm.verschuldung, de, "low")}
        <tr><td>Erwartetes KGV</td><td class="r num">${kgv(f.kgv_erwartet)}</td><td></td></tr>
        <tr><td>Gewinnwachstum</td><td class="r num">${frac(f.gewinnwachstum)}</td><td></td></tr>
        <tr><td>Marktkapitalisierung</td><td class="r num">${big(f.marktkap)}</td><td></td></tr>
        <tr><td>Kursziel Analysten (Ø)</td><td class="r num">${f.kursziel_analysten ? nf(f.kursziel_analysten) : "–"}</td><td class="r">${esc(f.analysten || "")}</td></tr>
      </table><p class="note">${esc(f.sektor)}${f.branche ? " · " + esc(f.branche) : ""}${bm.n ? ` · Vergleich mit ${bm.n} Werten` : ""}</p>
      ${f.beschreibung ? `<p class="note">${esc(f.beschreibung)}…</p>` : ""}</div>

      <h2>Technische Lage</h2>
      <div class="card"><table>
        <tr><td>Trend</td><td class="r">${esc(t.trend)}</td></tr>
        <tr><td>RSI (14)</td><td class="r num">${nf(t.rsi, 0)}${t.rsi > 70 ? " · überkauft" : t.rsi < 30 ? " · überverkauft" : ""}</td></tr>
        <tr><td>50-Tage-Linie</td><td class="r num">${nf(t.sma50)} ${t.ueber_sma50 ? "· Kurs darüber ✅" : "· Kurs darunter"}</td></tr>
        <tr><td>200-Tage-Linie</td><td class="r num">${nf(t.sma200)} ${t.ueber_sma200 ? "· Kurs darüber ✅" : "· Kurs darunter"}</td></tr>
        <tr><td>52-Wochen-Hoch</td><td class="r num">${nf(t.high52)} (${pct(t.abstand_high52_pct)})</td></tr>
        <tr><td>Volumen</td><td class="r num">${big(t.volumen)} (Ø ${big(t.avg_volumen20)})</td></tr>
      </table></div>

      ${a.news?.length ? `<h2>Nachrichten</h2><div class="card news">${a.news.map((n) => `<a href="${esc(n.url || "#")}" target="_blank" rel="noopener">${esc(n.title)}<small>${esc(n.publisher || "")} · ${dateTime(n.time)}</small></a>`).join("")}</div>` : ""}
      <p class="note" style="margin-top:18px">${esc(a.disclaimer)}</p>`;
  }

  async function status() {
    const s = (await tryLoad("status")) || {};
    const errs = s.errors || [];
    const sc = s.selfcheck;
    return `<h1>Systemstatus</h1>${DEMO ? `<p class="note">Vorschau mit Beispieldaten.</p>` : ""}
      <div class="card"><table>
        <tr><td>Letzter Scan</td><td class="r">${ago(s.last_scan)}</td></tr>
        <tr><td>Ergebnis</td><td class="r">${esc(s.last_scan_result || "–")}</td></tr>
        <tr><td>Börsen offen</td><td class="r">${(s.markets_open || []).map((m) => (m === "DE" ? "Xetra" : "USA")).join(", ") || "keine"}</td></tr>
        <tr><td>Überwachte Aktien</td><td class="r num">${s.universe_size ?? "–"}</td></tr>
        <tr><td>Basisdaten</td><td class="r">${ago(s.baseline_built)}</td></tr>
        <tr><td>Fundamentaldaten</td><td class="r">${ago(s.fundamentals_updated)}</td></tr>
        <tr><td>Watchlist</td><td class="r">${ago(s.watchlist_updated)}</td></tr>
        <tr><td>Selbstprüfung</td><td class="r">${sc ? (sc.problems.length ? `<span class="err">${sc.problems.length} Problem(e)</span>` : "✅ OK") + " · " + ago(sc.time) : "–"}</td></tr>
        <tr><td>Version</td><td class="r">${esc(s.version || "–")}</td></tr>
      </table></div>
      ${sc && sc.problems.length ? `<div class="card">${sc.problems.map((p) => `<p class="err" style="margin:4px 0">• ${esc(p)}</p>`).join("")}</div>` : ""}
      <h2>Letzte Fehler</h2>
      <div class="card">${errs.length ? errs.slice(0, 5).map((e) => `<p style="margin:4px 0"><b>${dateTime(e.time)}</b> · ${esc(e.job)}<br><span class="note">${esc(e.message)}</span></p>`).join("") : `<span class="note">Keine Fehler protokolliert.</span>`}</div>
      <h2>So funktioniert's</h2>
      <div class="card note">
        <p>• Gescannt wird alle 5 Minuten während der Handelszeiten von Xetra (9:00–17:30) und US-Börsen (15:30–22:00 MEZ). Die Kurse sind bis zu ~15 Minuten verzögert.</p>
        <p>• Alarm bei Tagesanstieg ≥ 10 % und Volumen ≥ 2× des 20-Tage-Schnitts (auf den Handelstag hochgerechnet). Pro Aktie und Tag gibt es höchstens einen weiteren Alarm, wenn sie nochmals 5 %-Punkte zulegt.</p>
        <p>• Die Bewertung ist regelbasiert: Volumen, Nachrichtenlage, RSI, Trend, Wachstum, Bewertung im Branchenvergleich und Verschuldung.</p>
        <p>• Die Push-Nachricht selbst kommt über die App <b>ntfy</b> auf den Sperrbildschirm. Ein Tippen darauf öffnet hier die passende Analyse.</p>
        <p><b>Wichtig:</b> Das Radar ist eine Entscheidungshilfe, keine Anlageberatung.</p>
      </div>`;
  }

  // ---- Router --------------------------------------------------------------
  async function render() {
    const hash = location.hash || "#/";
    const tab = hash.startsWith("#/watch") ? "watch" : hash.startsWith("#/history") ? "history" : hash.startsWith("#/status") ? "status" : "home";
    document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab && !hash.startsWith("#/a/")));
    try {
      let html;
      if (hash.startsWith("#/a/")) html = await detail(decodeURIComponent(hash.slice(4)));
      else if (tab === "watch") html = await watch();
      else if (tab === "history") html = await history();
      else if (tab === "status") html = await status();
      else html = await home();
      $view.innerHTML = html;
    } catch (e) {
      $view.innerHTML = empty("Daten konnten nicht geladen werden", `${esc(e.message)}<br>Prüfe die Internetverbindung oder schau unter „Status“.`);
    }
    updatePill();
  }

  async function updatePill() {
    const s = await tryLoad("status");
    if (!s) { $pill.innerHTML = `<span class="dot err"></span>keine Daten`; return; }
    const mins = s.last_scan ? (Date.now() - new Date(s.last_scan)) / 60000 : Infinity;
    const open = (s.markets_open || []).length > 0;
    const problem = s.selfcheck?.problems?.length || s.ok === false;
    const cls = problem ? "warn" : (!open || mins < 20 ? "ok" : "warn");
    const txt = DEMO ? "Demo-Daten" : open ? `Scan ${ago(s.last_scan)}` : "Börsen geschlossen";
    $pill.innerHTML = `<span class="dot ${cls}"></span>${txt}`;
  }

  $pill.addEventListener("click", () => { location.hash = "#/status"; });
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { Object.keys(cache).forEach((k) => delete cache[k]); render(); } });
  setInterval(() => { if (!document.hidden && !location.hash.startsWith("#/a/")) { Object.keys(cache).forEach((k) => delete cache[k]); render(); } }, 60000);
  if ("serviceWorker" in navigator && !DEMO) navigator.serviceWorker.register("sw.js").catch(() => {});
  render();
})();
