/* Aktien-Radar – Web-App (PWA). Liest die Daten, die der Scanner im Branch
   "data" ablegt, direkt von raw.githubusercontent.com. */
(() => {
  "use strict";

  // ---- Datenquelle bestimmen ---------------------------------------------
  const params = new URLSearchParams(location.search);
  // Radar: Branch "data"; Daytrading: Branch "daytrade"; Kongress: Branch "congress"
  const RAW = (() => {
    if (params.get("data")) return params.get("data").replace(/\/?$/, "/");
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      const owner = host.split(".")[0];
      const repo = location.pathname.split("/").filter(Boolean)[0] || `${owner}.github.io`;
      return `https://raw.githubusercontent.com/${owner}/${repo}/`;
    }
    return "sample/"; // lokale Vorschau mit Beispieldaten
  })();
  const DEMO = RAW === "sample/";
  const DATA = DEMO ? RAW : `${RAW}data/public/`;
  const SAMPLE_STATUS = { daytrade: "status-daytrade", congress: "status-congress" };
  const url = (name, branch) => {
    if (DEMO) return `sample/${branch !== "data" && name === "status" ? SAMPLE_STATUS[branch] : name}.json`;
    return `${RAW}${branch}/public/${name}.json`;
  };

  const $view = document.getElementById("view");
  const $pill = document.getElementById("statusPill");
  const cache = {};

  async function load(name, branch = "data", fresh = false) {
    const key = `${branch}/${name}`;
    if (!fresh && cache[key] && Date.now() - cache[key].t < 30000) return cache[key].d;
    const r = await fetch(`${url(name, branch)}?t=${Math.floor(Date.now() / 60000)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    const d = await r.json();
    cache[key] = { d, t: Date.now() };
    return d;
  }
  const tryLoad = (name, branch = "data") => load(name, branch).catch(() => null);

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


  // ---- Daytrading (USA) ----------------------------------------------------
  const ENTRY_TAG = { triggered: "ok", waiting: "", expired: "dim", "no-data": "dim", error: "warn" };
  const usd = (x) => (x == null ? "–" : `${nf(x)} $`);
  const pc0 = (x) => (x == null ? "–" : `${nf(x * 100, 0)} %`);
  const h24 = (t) => { const m = /^(\d{1,2}):(\d{2})\s*([AP])M$/i.exec(String(t || "").trim()); if (!m) return t || "";
    let h = +m[1] % 12; if (m[3].toUpperCase() === "P") h += 12; return `${String(h).padStart(2, "0")}:${m[2]}`; };
  const nyNow = () => new Date().toLocaleTimeString("de-DE", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });

  function oddsBar(tm) {
    if (!tm || tm.error) return tm?.error ? `<p class="note">Time Machine nicht möglich: ${esc(tm.error)}</p>` : "";
    return `<div class="odds" role="img" aria-label="Ziel zuerst ${pc0(tm.p_target)}, Stop zuerst ${pc0(tm.p_stop)}, offen ${pc0(tm.p_neither)}">
        <i class="t" style="width:${tm.p_target * 100}%"></i><i class="s" style="width:${tm.p_stop * 100}%"></i><i class="n" style="width:${tm.p_neither * 100}%"></i></div>
      <div class="legend"><span>Ziel zuerst <b>${pc0(tm.p_target)}</b></span><span>Stop zuerst <b>${pc0(tm.p_stop)}</b></span><span>offen <b>${pc0(tm.p_neither)}</b></span><span>→ <b>${esc(tm.verdict)}</b></span></div>`;
  }

  function entryCard(e) {
    const t = e.trigger, p = e.plan;
    const href = e.tm?.id ? `#/tm/${encodeURIComponent(e.tm.id)}` : null;
    const body = `<div class="row"><div class="grow"><div class="sym">${esc(e.symbol)} <span class="tag ${ENTRY_TAG[e.status] ?? ""}">${esc(e.status_de || e.status)}</span></div>
        <div class="name">${esc(e.name)}${e.setups?.length ? " · " + esc(e.setups.join(", ")) : ""}</div></div>
        ${t ? `<div style="text-align:right"><div class="chg up num">${usd(t.price)}</div><div class="name num">${esc(t.time_et)} ET · ${esc(t.time_berlin)} bei dir</div></div>` : ""}</div>
      <p class="note" style="margin:8px 0 0">${esc(e.reason || "")}</p>
      ${p ? `<div class="meta"><span>Stop ${usd(p.stop)}</span><span>Ziel ${usd(p.target)} (${nf(p.target_r, 0)}R)</span><span>Risiko ${usd(p.risk_per_share)}/Aktie</span></div>` : ""}
      ${t ? oddsBar(e.tm) : ""}${e.push_note ? `<p class="note" style="margin:6px 0 0">🔕 ${esc(e.push_note)}</p>` : e.pushed ? `<p class="note" style="margin:6px 0 0">🔔 Push gesendet</p>` : ""}`;
    return href ? `<a class="card" href="${href}">${body}</a>` : `<div class="card">${body}</div>`;
  }

  async function daytrade() {
    const [st, en, orb, se] = await Promise.all([tryLoad("status", "daytrade"), tryLoad("entries", "daytrade"),
      tryLoad("orb", "daytrade"), tryLoad("setups", "daytrade")]);
    let html = `<h1>Daytrading USA</h1><p class="sub">${esc(st?.message || "Noch keine Daten – der erste Lauf startet vor der US-Eröffnung (15:30 Uhr bei dir).")}
      ${st?.last_cycle ? ` · Takt ${ago(st.last_cycle)}` : ""} · New York ${nyNow()}</p>`;
    const items = en?.items || [];
    html += `<h2>Entry-Timer · ${items.length} Setups im Blick</h2>`;
    html += items.length ? items.map(entryCard).join("")
      : empty("Noch keine beobachteten Setups", "Vor Börsenstart sucht der Scanner die besten Setups, ab 9:50 New York (15:50 bei dir) prüft der Entry-Timer jede 5-Minuten-Kerze.");
    if (en?.plan_rule) html += `<p class="note">Einstieg = erste 5-Min.-Kerze, die über dem Hoch der ersten 15 Minuten schließt (${esc(en.window?.[0])}–${esc(en.window?.[1])} ET). Plan: ${esc(en.plan_rule)}.</p>`;

    const hits = orb?.hits || [];
    const c = orb?.counts;
    html += `<h2>Opening-Range-Breakouts · ${hits.length}</h2>`;
    if (c) html += `<p class="note">${c.scanned ?? 0} liquide Aktien geprüft, Stand ${esc(c.as_of || "–")} ET${c.unconfirmed ? `, ${c.unconfirmed} nicht mehr bestätigt` : ""}.</p>`;
    html += hits.length ? `<div class="card scroll"><table><tr><th>Zeit (ET)</th><th>Aktie</th><th class="r">Kurs</th><th class="r">Time Machine</th></tr>
      ${hits.slice().reverse().slice(0, 60).map((h) => `<tr><td class="num">${esc(h.time_et)}<br><span class="name">${esc(h.time_berlin)} MEZ</span></td>
        <td><b>${esc(h.symbol)}</b><br><span class="name">${esc(h.name)}</span></td>
        <td class="r num">${usd(h.price)}<br><span class="name">${pct(h.pct_over, 2)}</span></td>
        <td class="r" style="font-size:13px">${h.tm?.id ? `<a href="#/tm/${encodeURIComponent(h.tm.id)}">${esc(h.tm.verdict)} ›</a>` : "–"}</td></tr>`).join("")}</table></div>`
      : empty("Noch keine Ausbrüche", "Der ORB-Scan läuft ab 9:50 New York alle 10 Minuten, ab 11 Uhr alle 30 Minuten.");

    const sh = se?.hits || [];
    html += `<h2>Setups vor Börsenstart · ${se?.hits_total ?? 0}</h2>`;
    if (se) {
      html += `<p class="note">${nf(se.scanned, 0)} von ${nf(se.universe, 0)} US-Aktien geprüft (ab ${nf(se.filters?.min_price, 0)} $ und ${nf((se.filters?.min_volume || 0) / 1e6, 0)} Mio. Stück Volumen), Schlusskurse bis ${se.as_of ? new Date(se.as_of).toLocaleDateString("de-DE") : "–"}.</p>
        <div class="chips">${Object.entries(se.per_setup || {}).map(([k, v]) => `<span class="tag">${esc(k)}: ${v}</span>`).join("")}</div>`;
    }
    html += sh.length ? `<div class="card scroll"><table><tr><th>Aktie</th><th>Setup</th><th class="r">Kurs</th><th class="r">RSI</th></tr>
      ${sh.slice(0, 40).map((h) => `<tr><td><b>${esc(h.symbol)}</b>${(se.watch || []).includes(h.symbol) ? " 👁" : ""}<br><span class="name">${esc(h.name)}</span></td>
        <td style="font-size:13px">${esc((h.labels || []).join(", "))}</td><td class="r num">${usd(h.price)}</td><td class="r num">${nf(h.rsi, 0)}</td></tr>`).join("")}</table></div>
      <p class="note">👁 = wird vom Entry-Timer beobachtet. ${esc(se.hinweis || "")}</p>`
      : empty("Noch keine Setups", "Sie werden an jedem US-Handelstag vor Börsenstart berechnet.");
    html += `<p class="note" style="margin-top:18px">${esc(en?.disclaimer || "Keine Anlageberatung.")}</p>`;
    return html;
  }

  function fanChart(tm) {
    const m = tm.mc, p = tm.plan, bands = m.bands || [], times = m.band_times || [];
    if (bands.length < 2) return "";
    const W = 400, H = 230, L = 46, R = 8, T = 10, B = 22;
    const vals = bands.flat().concat([p.stop, p.target, p.entry]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const x = (i) => L + (i / (bands.length - 1)) * (W - L - R);
    const y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
    const area = (a, b) => bands.map((q, i) => `${x(i)},${y(q[a])}`).join(" ") + " " + bands.map((q, i) => `${x(i)},${y(q[b])}`).reverse().join(" ");
    const line = (k) => bands.map((q, i) => `${x(i)},${y(q[k])}`).join(" ");
    const hl = (v, col, lab) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="${col}" stroke-dasharray="4 4" stroke-width="1.3"/>
      <text x="${L - 6}" y="${y(v) + 3.5}" text-anchor="end" style="fill:${col}">${nf(v)}</text><text x="${W - R - 2}" y="${y(v) - 4}" text-anchor="end" style="fill:${col}">${lab}</text>`;
    const ticks = [0, Math.floor((bands.length - 1) / 2), bands.length - 1];
    return `<svg class="fan" viewBox="0 0 ${W} ${H}" role="img" aria-label="Fächer der 2.000 simulierten Kursverläufe">
      <polygon points="${area(0, 4)}" fill="var(--accent)" opacity=".14"/>
      <polygon points="${area(1, 3)}" fill="var(--accent)" opacity=".28"/>
      <polyline points="${line(2)}" fill="none" stroke="var(--accent)" stroke-width="2"/>
      ${hl(p.target, "var(--green)", "Ziel")}${hl(p.stop, "var(--red)", "Stop")}
      <text x="${L - 6}" y="${y(p.entry) + 3.5}" text-anchor="end">${nf(p.entry)}</text>
      ${ticks.map((i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === bands.length - 1 ? "end" : "middle"}">${esc(times[i] || "")} ET</text>`).join("")}
    </svg><p class="note">Linie = Median, dunkle Fläche = mittlere Hälfte, helle Fläche = 90 % der Verläufe.</p>`;
  }

  async function tmDetail(id) {
    const tm = await load(`tm/${id}`, "daytrade");
    const p = tm.plan, m = tm.mc, h = tm.history || {}, s = tm.summary || {};
    const trades = (h.trades || []).slice(-12).reverse();
    const OUT = { target: "Ziel", stop: "Stop", close: "offen" };
    return `<a class="back" href="#/daytrade">‹ Daytrading</a>
      <div class="card"><div class="row"><div class="grow"><div class="sym" style="font-size:20px">${esc(p.symbol)} · Time Machine</div>
        <div class="name">${tm.kind === "o" ? "ORB-Scanner" : "Entry-Timer"} · ${new Date(p.date).toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" })}</div></div></div>
        <div class="meta"><span>Einstieg <b>${usd(p.entry)}</b> um ${esc(h24(p.entry_time))} ET</span><span>Stop ${usd(p.stop)}</span><span>Ziel ${usd(p.target)} (${nf(p.target_r, 0)}R)</span><span>glatt bis ${esc(m.until)} ET</span></div></div>
      <h2>${nf(m.replays, 0)} Durchläufe des restlichen Handelstags</h2>
      <div class="kpis"><div class="kpi t"><div class="v num">${pc0(m.p_target)}</div><div class="l">Ziel zuerst</div></div>
        <div class="kpi s"><div class="v num">${pc0(m.p_stop)}</div><div class="l">Stop zuerst</div></div>
        <div class="kpi"><div class="v num">${pc0(m.p_neither)}</div><div class="l">bis ${esc(m.until)} offen</div></div></div>
      <div class="card" style="margin-top:10px"><b>${esc(s.verdict || "")}</b>
        <p class="note" style="margin:6px 0 0">Im Plus am Ende: ${pc0(m.p_green)} · Ø Ergebnis ${nf(m.avg_R, 2)} R · Kurs um ${esc(m.until)}: Median ${usd(m.median_close)}, 90 % zwischen ${usd(m.p5_close)} und ${usd(m.p95_close)}</p></div>
      <div class="card">${fanChart(tm)}</div>
      <h2>Wie oft hat dieselbe Regel früher funktioniert?</h2>
      <div class="card">${h.triggered ? `<p style="margin:0">In den letzten <b>${h.sessions}</b> Handelstagen hat dieselbe Regel <b>${h.triggered}×</b> ausgelöst:
        <span class="buy">${h.target}× Ziel</span>, <span class="sell">${h.stop}× Stop</span>, ${h.close}× offen. Ø ${nf(h.avg_R, 2)} R.</p>
        <table style="margin-top:8px"><tr><th>Tag</th><th class="r">Einstieg</th><th class="r">Ergebnis</th></tr>
        ${trades.map((x) => `<tr><td class="num">${new Date(x.date).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} · ${esc(h24(x.time))}</td><td class="r num">${usd(x.entry)}</td>
          <td class="r num ${x.outcome === "target" ? "buy" : x.outcome === "stop" ? "sell" : ""}">${OUT[x.outcome] || x.outcome} (${nf(x.R, 2)} R)</td></tr>`).join("")}</table>`
        : `<span class="note">${esc(h.note || "Die Regel hat in den vergangenen Tagen nicht ausgelöst.")}</span>`}</div>
      <p class="note">Jeder Durchlauf setzt den Rest des Tages aus echten 5-Minuten-Kerzen dieser Aktie zur gleichen Uhrzeit zusammen (${m.pool_sessions} Handelstage, ${esc(m.pool_from)} bis ${esc(m.pool_to)}). Berührt eine Kerze Stop und Ziel, zählt der Stop. Eine Simulation ist keine Prognose: Zahlen, Nachrichten oder Handelsstopps können anders verlaufen als in den letzten 60 Tagen.</p>
      <p class="note">${esc(tm.disclaimer || "")}</p>`;
  }

  // ---- Kongress -----------------------------------------------------------
  async function kongress() {
    const c = await tryLoad("congress", "congress");
    const fil = c?.filings || [];
    let html = `<h1>Kongress-Aktiengeschäfte</h1><p class="sub">Meldungen von Abgeordneten des US-Repräsentantenhauses · aktualisiert ${dateTime(c?.updated)}</p>
      <p class="note">⚠️ ${esc(c?.hinweis || "Öffentliche Pflichtmeldungen, bis zu 45 Tage nach dem Geschäft.")}</p>`;
    const top = c?.top || [];
    if (top.length) {
      html += `<h2>Meistgehandelt (30 Tage)</h2><div class="card scroll"><table><tr><th>Ticker</th><th class="r">Käufe</th><th class="r">Verkäufe</th><th>Wer</th></tr>
        ${top.slice(0, 12).map((t) => `<tr><td><b>${esc(t.ticker)}</b><br><span class="note">${esc(t.asset || "")}</span></td><td class="r num buy">${t.kaeufe}</td><td class="r num sell">${t.verkaeufe}</td>
          <td style="font-size:12.5px">${esc(t.members.map((m) => m.replace(/^Hon\.\s*/, "")).slice(0, 3).join(", "))}${t.members.length > 3 ? " …" : ""}</td></tr>`).join("")}</table></div>`;
    }
    html += `<h2>Neueste Meldungen · ${fil.length}</h2>`;
    html += fil.length ? fil.slice(0, 80).map((f) => `<div class="card">
        <div class="row"><div class="grow"><div class="sym">${f.focus ? "⭐ " : ""}${esc(f.name.replace(/^Hon\.\s*/, ""))} <span class="tag">${esc(f.district)}</span></div>
          <div class="name">gemeldet ${new Date(f.filed).toLocaleDateString("de-DE")} · <a href="${esc(f.url)}" target="_blank" rel="noopener">PDF</a></div></div></div>
        ${f.rows.length ? f.rows.slice(0, 12).map((r) => `<div class="trow"><span class="${r.type === "P" ? "buy" : r.type?.startsWith("S") ? "sell" : ""}">${esc(r.type_de)}</span>
            <b>${esc(r.ticker || "")}</b> ${esc(r.asset || "")}${r.asset_type && r.asset_type !== "Aktie" ? ` <span class="tag">${esc(r.asset_type)}</span>` : ""}
            <div class="meta" style="margin-top:2px"><span>${esc(r.amount || "")}</span><span>gehandelt ${r.date ? new Date(r.date).toLocaleDateString("de-DE") : "–"}</span>
            ${r.days_to_disclose != null ? `<span class="${r.late ? "err" : ""}">${r.days_to_disclose} Tage bis zur Meldung${r.late ? " (verspätet)" : ""}</span>` : ""}<span>${esc(r.owner || "")}</span></div>
            ${r.option ? `<div class="note">${r.option.contracts} ${r.option.kind === "call" ? "Call" : "Put"}-Optionen, Basispreis ${nf(r.option.strike)} $, Verfall ${new Date(r.option.expires).toLocaleDateString("de-DE")}</div>` : ""}</div>`).join("")
            + (f.rows.length > 12 ? `<p class="note">… und ${f.rows.length - 12} weitere Positionen im PDF.</p>` : "")
          : `<p class="note" style="margin:8px 0 0">Nicht automatisch lesbar (z. B. eingescannte Papiermeldung) – bitte das PDF öffnen.</p>`}
      </div>`).join("") : empty("Noch keine Meldungen", "Das Archiv des House Clerk wird dreimal pro Werktag geprüft.");
    html += `<p class="note">${esc(c?.senat || "")} Quelle: ${esc(c?.quelle || "disclosures-clerk.house.gov")}.</p>`;
    return html;
  }

  async function status() {
    const [s0, dt, cg] = await Promise.all([tryLoad("status"), tryLoad("status", "daytrade"), tryLoad("status", "congress")]);
    const s = s0 || {};
    const dtErr = (dt?.errors || []).slice(0, 3);
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
      <h2>Daytrading & Kongress</h2>
      <div class="card"><table>
        <tr><td>Daytrading-Takt</td><td class="r">${ago(dt?.last_cycle)}</td></tr>
        <tr><td>Stand</td><td class="r">${esc(dt?.message || "–")}</td></tr>
        <tr><td>US-Aktien im Scanner</td><td class="r num">${dt?.universe_size ? nf(dt.universe_size, 0) : "–"}</td></tr>
        <tr><td>Kongress-Meldungen</td><td class="r">${ago(cg?.congress_last)}${cg?.congress_filings != null ? ` · ${cg.congress_filings} im Archiv` : ""}</td></tr>
      </table>${dtErr.length ? dtErr.map((e) => `<p style="margin:6px 0 0"><b>${dateTime(e.time)}</b> · Daytrading<br><span class="note">${esc(e.message)}</span></p>`).join("") : ""}</div>
      <h2>Letzte Fehler</h2>
      <div class="card">${errs.length ? errs.slice(0, 5).map((e) => `<p style="margin:4px 0"><b>${dateTime(e.time)}</b> · ${esc(e.job)}<br><span class="note">${esc(e.message)}</span></p>`).join("") : `<span class="note">Keine Fehler protokolliert.</span>`}</div>
      <h2>So funktioniert's</h2>
      <div class="card note">
        <p>• Gescannt wird alle 5 Minuten während der Handelszeiten von Xetra (9:00–17:30) und US-Börsen (15:30–22:00 MEZ). Die Kurse sind bis zu ~15 Minuten verzögert.</p>
        <p>• Alarm bei Tagesanstieg ≥ 10 % und Volumen ≥ 2× des 20-Tage-Schnitts (auf den Handelstag hochgerechnet). Pro Aktie und Tag gibt es höchstens einen weiteren Alarm, wenn sie nochmals 5 %-Punkte zulegt.</p>
        <p>• Die Bewertung ist regelbasiert: Volumen, Nachrichtenlage, RSI, Trend, Wachstum, Bewertung im Branchenvergleich und Verschuldung.</p>
        <p>• Die Push-Nachricht selbst kommt über die App <b>ntfy</b> auf den Sperrbildschirm. Ein Tippen darauf öffnet hier die passende Analyse.</p>
        <p>• <b>Daytrading (nur US-Börsen):</b> Vor Börsenstart durchsucht der Setup-Scanner rund 5.900 US-Aktien. Ab 9:50 New York (15:50 bei dir) prüft der Entry-Timer alle 5 Minuten die beobachteten Setups und meldet den Einstieg per Push; die Time Machine spielt jeden Einstieg 10.000-mal durch. Es wird nie automatisch gekauft.</p>
        <p>• <b>Kongress:</b> Dreimal pro Werktag werden neue Pflichtmeldungen von US-Abgeordneten gelesen; neue Aktiengeschäfte kommen als Sammel-Push.</p>
        <p><b>Wichtig:</b> Das Radar ist eine Entscheidungshilfe, keine Anlageberatung.</p>
      </div>`;
  }

  // ---- Router --------------------------------------------------------------
  async function render() {
    const hash = location.hash || "#/";
    const tab = hash.startsWith("#/watch") ? "watch" : hash.startsWith("#/history") ? "history" : hash.startsWith("#/status") ? "status"
      : hash.startsWith("#/daytrade") || hash.startsWith("#/tm/") ? "daytrade" : hash.startsWith("#/kongress") ? "kongress" : "home";
    document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab && !hash.startsWith("#/a/")));
    try {
      let html;
      if (hash.startsWith("#/a/")) html = await detail(decodeURIComponent(hash.slice(4)));
      else if (hash.startsWith("#/tm/")) html = await tmDetail(decodeURIComponent(hash.slice(5)));
      else if (tab === "daytrade") html = await daytrade();
      else if (tab === "kongress") html = await kongress();
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
  setInterval(() => { if (!document.hidden && !/^#\/(a|tm)\//.test(location.hash)) { Object.keys(cache).forEach((k) => delete cache[k]); render(); } }, 60000);
  if ("serviceWorker" in navigator && !DEMO) navigator.serviceWorker.register("sw.js").catch(() => {});
  render();
})();
