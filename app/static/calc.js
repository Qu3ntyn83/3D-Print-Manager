"use strict";
/* ---------- Kalkulation & Angebote (aus dem 3D Print Calculator) ----------
   Filamentpreise und Bestand kommen aus dem Inventar, Drucker aus dem Bambu-Konto,
   3MF-Dateien aus der Bibliothek oder per Upload. */
const CX = { cfg: null, fils: [], printers: [], kwh: 0.35, job: null, sub: store.get("cxSub", "calc"), libModels: null, libSel: null, saveT: null, quoteModel: null };
const CX_CURRENCIES = [["EUR", "Euro"], ["USD", "US-Dollar"], ["GBP", "Britisches Pfund"], ["CHF", "Schweizer Franken"], ["PLN", "Polnischer Złoty"],
  ["CZK", "Tschechische Krone"], ["SEK", "Schwedische Krone"], ["DKK", "Dänische Krone"], ["NOK", "Norwegische Krone"], ["HUF", "Forint"],
  ["CAD", "Kanadischer Dollar"], ["AUD", "Australischer Dollar"], ["JPY", "Yen"], ["CNY", "Renminbi"]];
const CX_CATS = [["mat", "Material", "--cx-mat"], ["strom", "Strom", "--cx-strom"], ["masch", "Maschine", "--cx-masch"], ["wear", "Verschleiß", "--cx-wear"],
  ["labor", "Arbeitszeit", "--cx-labor"], ["extra", "Zubehör", "--cx-extra"], ["risk", "Fehldruck-Risiko", "--cx-risk"]];
const CX_SENDER = [["name", "Name"], ["company", "Firma / Marke"], ["mail", "E-Mail"], ["street", "Straße & Nr."], ["zip", "PLZ"], ["city", "Ort"],
  ["phone", "Telefon"], ["web", "Webseite"], ["taxid", "Steuernr. / USt-IdNr."], ["bank", "Bank"], ["iban", "IBAN"]];

const cxCur = () => (CX.cfg && CX.cfg.settings.cur) || "EUR";
const cxMoney = v => (isFinite(v) ? v : 0).toLocaleString("de-DE", { style: "currency", currency: cxCur() });
const cxNum = (v, d = 2) => (+v || 0).toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
const cxSym = () => { try { return new Intl.NumberFormat("de-DE", { style: "currency", currency: cxCur() }).formatToParts(0).find(x => x.type === "currency").value; } catch { return cxCur(); } };
const cxVal = id => ($(id) ? $(id).value.trim() : "");

/* ---------- Auftrag (Entwurf bleibt im Browser) ---------- */
function cxNewJob() {
  const d = (CX.cfg && CX.cfg.defaults) || {};
  return { file: "", meta: "", source: "manual", plate: 0, title: "",
    plates: [{ n: 1, hours: 2, ppp: 1, purge: 0, lines: [{ slot: "#1", grams: 50, fil: CX.fils[0] ? CX.fils[0].id : null, manual: true }] }],
    printer: d.printer || (CX.printers[0] && CX.printers[0].key), profile: d.profile || "priv", qty: 1, prep: d.prep ?? 10, post: d.post ?? 3, extras: [] };
}
const cxSaveJob = () => store.set("cxJob", CX.job);
const cxPlate = () => CX.job.plates[CX.job.plate] || CX.job.plates[0];
/* Berechnet wird das komplette Projekt (alle Platten = ein Stück) oder nur die gewählte Platte */
const cxScope = () => CX.job.plates.length > 1 && CX.job.scope === "plate" ? "plate" : "all";
const cxCalcPlates = () => cxScope() === "plate" ? [cxPlate()] : CX.job.plates;
const cxFil = id => CX.fils.find(f => f.id === id) || null;
const cxPrinter = () => CX.printers.find(p => p.key === CX.job.printer) || CX.printers[0] || { name: "–", price: 0, life: 5000, watt: 0, wear: 0 };
const cxProfile = () => CX.cfg.profiles.find(p => p.id === CX.job.profile) || CX.cfg.profiles[0];
const cxPerKg = id => { const f = cxFil(id); return f && f.price_kg != null ? f.price_kg : 0; };

function cxRound(u) {
  const r = CX.cfg.settings.round;
  if (r === "none") return u;
  if (r === "0.99") { const b = Math.floor(u) + 0.99; return b >= u - 1e-9 ? b : b + 1; }
  const step = +r || 0.01; return Math.ceil((u - 1e-9) / step) * step;
}
function cxCalc(qty) {
  const P = cxPrinter(), R = cxProfile(), st = CX.cfg.settings;
  const parts = { mat: 0, strom: 0, masch: 0, wear: 0, labor: 0, extra: 0 };
  let h = 0, plates = 0, grams = 0;
  for (const p of cxCalcPlates()) {
    const ppp = Math.max(1, p.ppp | 0), runs = Math.ceil(qty / ppp), ph = p.hours / ppp * qty;
    const plateMat = p.lines.reduce((a, l) => a + l.grams * cxPerKg(l.fil) / 1000, 0) + (p.lines[0] ? p.purge * cxPerKg(p.lines[0].fil) / 1000 : 0);
    parts.mat += plateMat / ppp * qty;
    parts.strom += ph * (+P.watt || 0) / 1000 * CX.kwh;
    parts.masch += ph * (+P.price || 0) / Math.max(1, +P.life || 1);
    parts.wear += ph * (+P.wear || 0);
    if (R.rate > 0) parts.labor += runs * CX.job.prep / 60 * R.rate;          // Rüsten je Plattendurchlauf
    h += ph; plates += runs;
    grams += (p.lines.reduce((a, l) => a + l.grams, 0) + (p.lines.length ? p.purge : 0)) / ppp * qty;
  }
  if (R.rate > 0) parts.labor += qty * CX.job.post / 60 * R.rate;            // Nacharbeit je fertigem Teil
  parts.extra = qty * CX.job.extras.reduce((a, x) => a + x.price * x.n, 0);
  parts.risk = (parts.mat + parts.strom + parts.masch + parts.wear) * R.risk / 100;
  const cost = Object.values(parts).reduce((a, b) => a + b, 0), net = cost * (1 + R.margin / 100);
  const gross = st.klein ? net : net * (1 + st.vat / 100), unit = cxRound(gross / qty);
  return { parts, cost, net, gross, unit, total: unit * qty, plates, h, grams };
}
function cxStock(qty) {
  const need = {};
  for (const p of cxCalcPlates()) {
    const ppp = Math.max(1, p.ppp | 0);
    p.lines.forEach((l, i) => { need[l.fil] = (need[l.fil] || 0) + l.grams / ppp * qty + (i === 0 ? p.purge / ppp * qty : 0); });
  }
  return Object.entries(need).map(([id, g]) => ({ f: cxFil(+id), g })).filter(x => x.f && x.f.stock_g < x.g);
}

/* ---------- Laden & Speichern ---------- */
async function cxLoad() {
  const d = await api("/api/calc/data");
  CX.cfg = d.config; CX.fils = d.filaments; CX.printers = d.printers; CX.kwh = d.kwh_price;
  const saved = store.get("cxJob", null);
  CX.job = saved && saved.plates && saved.plates.length ? saved : cxNewJob();
  if (!CX.printers.some(p => p.key === CX.job.printer)) CX.job.printer = CX.printers[0] && CX.printers[0].key;
  cxSetSub(CX.sub);
}
function cxSaveCfg() {
  clearTimeout(CX.saveT);
  CX.saveT = setTimeout(async () => {
    const c = CX.cfg;
    try {
      const r = await api("/api/calc/config", { method: "PUT", body: JSON.stringify({ settings: c.settings, sender: c.sender, logo: c.logo, profiles: c.profiles,
        printer_costs: c.printer_costs, manual_printers: c.manual_printers, defaults: { ...c.defaults, printer: CX.job.printer, profile: CX.job.profile } }) });
      CX.printers = r.printers;
    } catch (e) { toast("Speichern fehlgeschlagen: " + e.message); }
  }, 400);
}

/* ---------- Ansichten ---------- */
function cxSetSub(sub) {
  CX.sub = sub; store.set("cxSub", sub);
  $$("#cxNav button").forEach(b => b.classList.toggle("active", b.dataset.cx === sub));
  $$("#tab-calc .cx-view").forEach(v => v.hidden = v.id !== "cx-" + sub);
  if (sub === "calc") cxRenderCalc();
  if (sub === "quote") { cxRenderResult(); }
  if (sub === "costs") cxRenderCosts();
  if (sub === "sender") cxRenderSender();
}
function cxRenderCalc() {
  const j = CX.job, p = cxPlate();
  $("#cxFile").textContent = j.file || "Eigenes Projekt";
  $("#cxMeta").textContent = j.meta || "Werte eintragen oder eine 3MF laden";
  $("#cxPlateSrc").textContent = { manual: "manuelle Eingabe", library: "aus der Bibliothek", makerworld: "MakerWorld-Druckprofil" }[j.source] || "aus der 3MF";
  const multi = j.plates.length > 1, all = cxScope() === "all";
  $("#cxPlates").innerHTML = (multi ? `<div class="seg mini cx-scope" role="group" aria-label="Berechnen">
      <button type="button" data-scope="all" class="${all ? "active" : ""}">Komplett · ${j.plates.length} Platten · ${cxNum(j.plates.reduce((a, x) => a + (+x.hours || 0), 0))} h</button>
      <button type="button" data-scope="plate" class="${all ? "" : "active"}">Nur Platte ${p.n}</button></div>
      <span class="muted small cx-edit">${all ? "Bearbeiten:" : "Platte:"}</span>` : "") +
    (multi || j.source !== "manual" ? j.plates.map((x, i) =>
      `<button type="button" data-plate="${i}" class="${i === j.plate ? "active" : ""}">Platte ${x.n} · ${cxNum(x.hours)} h</button>`).join("") : "");
  $("#cxH").value = p.hours; $("#cxPpp").value = p.ppp; $("#cxPurge").value = p.purge;
  $("#cxPrinter").innerHTML = CX.printers.map(x => `<option value="${esc(x.key)}" ${x.key === j.printer ? "selected" : ""}>${esc(x.name)}</option>`).join("")
    || `<option value="">Kein Drucker – unter „Drucker & Profile“ anlegen</option>`;
  $("#cxProfile").innerHTML = CX.cfg.profiles.map(x => `<option value="${esc(x.id)}" ${x.id === j.profile ? "selected" : ""}>${esc(x.name)}</option>`).join("");
  $("#cxQty").value = j.qty; $("#cxPrep").value = j.prep; $("#cxPost").value = j.post;
  const opts = sel => CX.fils.map(f => `<option value="${f.id}" ${f.id === sel ? "selected" : ""}>${esc(f.name)} · ${esc(f.brand)}${f.price_kg == null ? " (ohne Preis)" : ""}${f.stock_g ? "" : " (leer)"}</option>`).join("");
  $("#cxLines").innerHTML = p.lines.map((l, i) => {
    const f = cxFil(l.fil), col = l.manual || !l.color ? (f ? f.color : "#888888") : l.color, typ = l.manual || !l.type ? (f ? f.material : "") : l.type;
    return `<tr><td><span class="cx-sw" style="background:${esc(col)}"></span><span class="cx-slot">${esc(l.slot)}</span> <span class="muted small">${esc(typ)}</span></td>
      <td><select data-line="${i}" aria-label="Filament für ${esc(l.slot)}">${opts(l.fil)}</select></td>
      <td class="n"><span class="cx-unit cx-g"><input type="number" data-grams="${i}" value="${l.grams}" min="0" step="0.1" aria-label="Gramm"><em>g</em></span></td>
      <td class="n mono" data-lcost="${i}">${cxMoney(l.grams * cxPerKg(l.fil) / 1000)}</td>
      <td class="n"><button type="button" class="ghost mini" data-ldel="${i}" aria-label="Filament entfernen">✕</button></td></tr>`;
  }).join("") || `<tr><td colspan="5" class="muted small">Kein Filament auf dieser Platte. Über „+ Filament“ hinzufügen.</td></tr>`;
  const del = $("#cxDelPlate"); del.hidden = j.plates.length < 2; del.textContent = `Platte ${p.n} entfernen`;
  $("#cxExtras").innerHTML = j.extras.map((x, i) => `<tr>
    <td><input data-xn="${i}" value="${esc(x.name)}" aria-label="Bezeichnung"></td>
    <td class="n"><span class="cx-unit"><input type="number" data-xp="${i}" value="${x.price}" step="0.01" min="0" aria-label="Stückpreis"><em>${esc(cxSym())}</em></span></td>
    <td class="n"><input type="number" data-xc="${i}" value="${x.n}" step="1" min="0" aria-label="Anzahl je Teil"></td>
    <td class="n"><button type="button" class="ghost mini" data-xdel="${i}" aria-label="Entfernen">✕</button></td></tr>`).join("");
  cxRenderResult();
}
function cxRenderResult() {
  if (!CX.job) return;
  const q = Math.max(1, CX.job.qty | 0), r = cxCalc(q), R = cxProfile(), st = CX.cfg.settings, total = r.cost || 1;
  const short = cxStock(q), noPrice = cxCalcPlates().flatMap(p => p.lines).filter(l => { const f = cxFil(l.fil); return f && f.price_kg == null; });
  const tiers = [1, 5, 10, 25, 50].map(n => ({ n, u: cxCalc(n).unit })), base = tiers[0].u;
  $("#cxResult").innerHTML = `
    <div class="cx-lbl">Stückpreis · ${esc(R.name)}</div>
    <div class="cx-price"><div class="cx-big">${cxNum(r.unit)}<small>${esc(cxSym())}</small></div>
      <div class="cx-side">Gesamt ${q} Stk<strong>${cxMoney(r.total)}</strong></div></div>
    <div class="cx-chips">
      <span class="pill">${st.klein ? "ohne USt (§ 19)" : `inkl. ${st.vat} % MwSt`}</span>
      ${CX.job.plates.length > 1 ? `<span class="pill">${cxScope() === "all" ? `komplett (${CX.job.plates.length} Platten je Stück)` : `nur Platte ${cxPlate().n}`}</span>` : ""}
      <span class="pill">${r.plates} ${r.plates === 1 ? "Platte" : "Platten"} · ${cxNum(r.h, 1)} h</span>
      <span class="pill">${cxNum(r.grams, 0)} g Filament</span>
      ${short.length ? short.map(s => `<span class="pill warn">Bestand knapp: ${esc(s.f.name)} (${cxNum(s.g, 0)} von ${s.f.stock_g} g)</span>`).join("") : `<span class="pill ok">Bestand reicht</span>`}
      ${noPrice.length ? `<span class="pill bad">Ohne Preis im Inventar: ${esc([...new Set(noPrice.map(l => cxFil(l.fil).name))].join(", "))}</span>` : ""}
    </div>
    <div class="cx-lbl">Selbstkosten ${cxMoney(r.cost)} · Marge ${R.margin} %</div>
    <div class="cx-bar" role="img" aria-label="Kostenaufteilung">${CX_CATS.map(([k, , c]) => `<span style="width:${r.parts[k] / total * 100}%;background:var(${c})"></span>`).join("")}</div>
    <table class="cx-legend"><tbody>
      ${CX_CATS.map(([k, n, c]) => `<tr><td><span class="cx-dot" style="background:var(${c})"></span></td><td>${n}</td><td class="n muted">${cxNum(r.parts[k] / total * 100, 0)} %</td><td class="n mono">${cxMoney(r.parts[k])}</td></tr>`).join("")}
      <tr class="sum"><td></td><td>Selbstkosten</td><td></td><td class="n mono">${cxMoney(r.cost)}</td></tr>
      <tr><td></td><td>+ Marge</td><td></td><td class="n mono">${cxMoney(r.net - r.cost)}</td></tr>
      ${st.klein ? "" : `<tr><td></td><td>+ MwSt</td><td></td><td class="n mono">${cxMoney(r.gross - r.net)}</td></tr>`}
      <tr><td></td><td>Rundung</td><td></td><td class="n mono">${cxMoney(r.total - r.gross)}</td></tr>
    </tbody></table>
    <div class="cx-lbl" style="margin-top:16px">Mengenstaffel</div>
    <table class="cx-tiers"><thead><tr><th>Menge</th><th class="n">Stückpreis</th><th class="n">Gesamt</th><th></th></tr></thead><tbody>
      ${tiers.map(x => `<tr class="${x.n === q ? "cur" : ""}"><td>${x.n} Stk</td><td class="n mono">${cxMoney(x.u)}</td><td class="n mono">${cxMoney(x.u * x.n)}</td><td class="n cx-save">${x.u < base ? "−" + cxNum((1 - x.u / base) * 100, 0) + " %" : ""}</td></tr>`).join("")}
    </tbody></table>
    <div class="cx-row"><button class="primary" type="button" id="cxToQuote">Angebot erstellen</button></div>`;
  cxRenderQuote(r, q);
}

/* ---------- Angebot ---------- */
const CX_DEF_LOGO = `<div class="cx-qbrand"><svg width="40" height="40" viewBox="0 0 64 64" aria-hidden="true"><use href="#psLogo"/></svg>
  <div><b>POWERSCRIPTING</b><small>Elevate. Automate. Innovate.</small></div></div>`;
function cxQuoteModel(r, q) {
  const sd = CX.cfg.sender, st = CX.cfg.settings, lines = cxCalcPlates().flatMap(x => x.lines);
  const title = cxVal("#cqTitle") || CX.job.title || "3D-Druck", no = cxVal("#cqNo") || "–";
  const cust = [cxVal("#cqCust"), cxVal("#cqContact") ? "z. Hd. " + cxVal("#cqContact") : "", cxVal("#cqStreet"), [cxVal("#cqZip"), cxVal("#cqCity")].filter(Boolean).join(" ")].filter(Boolean);
  const mats = [...new Set(lines.map(l => (cxFil(l.fil) || {}).name).filter(Boolean))].join(", ");
  const date = new Date().toLocaleDateString("de-DE"), valid = new Date(Date.now() + (st.valid || 14) * 864e5).toLocaleDateString("de-DE");
  const sendLine = [sd.company || sd.name, sd.street, [sd.zip, sd.city].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
  const cols = [[sd.name, sd.company !== sd.name ? sd.company : "", sd.street, [sd.zip, sd.city].filter(Boolean).join(" ")].filter(Boolean),
    [sd.mail, sd.phone ? "Tel. " + sd.phone : "", sd.web].filter(Boolean),
    [sd.bank, sd.iban ? "IBAN " + sd.iban : "", sd.taxid ? "St.-Nr. " + sd.taxid : ""].filter(Boolean)].filter(c => c.length);
  return { no, date, valid, title, cust, mail: cxVal("#cqMail"), sendLine, cols, logo: CX.cfg.logo,
    sub: [mats, "gefertigt auf " + cxPrinter().name].filter(Boolean).join(" · "),
    desc: CX.job.extras.length ? "3D-Druck inkl. Material, Zubehör und Nachbearbeitung" : "3D-Druck inkl. Material und Nachbearbeitung",
    qty: q, unit: cxMoney(r.unit), total: cxMoney(r.total),
    vatLine: st.klein ? null : `enthaltene MwSt ${st.vat} %`, vatAmount: st.klein ? null : cxMoney(r.total - r.total / (1 + st.vat / 100)),
    note: st.klein ? "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet." : null,
    labels: { quote: "Angebot", date: "Datum " + date, valid: "gültig bis " + valid, pos: "Pos.", desc: "Beschreibung", qty: "Menge", unit: "Einzelpreis", total: "Gesamt", sum: "Gesamtbetrag" } };
}
function cxRenderQuote(r, q) {
  const m = CX.quoteModel = cxQuoteModel(r, q);
  $("#cqPreview").innerHTML = `
    <div class="cx-qh">${m.logo ? `<div class="cx-qlogo"><img src="${m.logo}" alt="Logo"></div>` : CX_DEF_LOGO}
      <div class="cx-qmeta">${m.labels.quote} <b>${esc(m.no)}</b><br>${m.labels.date}<br>${m.labels.valid}</div></div>
    ${m.sendLine ? `<div class="cx-sendline">${esc(m.sendLine)}</div>` : `<div style="height:18px"></div>`}
    <div class="cx-addr">${m.cust.map((x, i) => i === 0 ? `<strong>${esc(x)}</strong>` : esc(x)).join("<br>") || `<span class="muted">Kundendaten oben eintragen</span>`}</div>
    ${m.mail ? `<div class="muted small">${esc(m.mail)}</div>` : ""}
    <h3>${esc(m.title)}</h3><p class="muted small">${esc(m.sub)}</p>
    <div class="cx-tbl"><table><thead><tr><th>${m.labels.pos}</th><th>${m.labels.desc}</th><th class="n">${m.labels.qty}</th><th class="n">${m.labels.unit}</th><th class="n">${m.labels.total}</th></tr></thead><tbody>
      <tr><td>1</td><td>${esc(m.title)}<br><span class="muted small">${m.desc}</span></td><td class="n">${m.qty}</td><td class="n mono">${m.unit}</td><td class="n mono">${m.total}</td></tr>
      ${m.vatLine ? `<tr><td></td><td class="muted small">${m.vatLine}</td><td></td><td></td><td class="n mono">${m.vatAmount}</td></tr>` : ""}
      <tr class="sum"><td></td><td>${m.labels.sum}</td><td></td><td></td><td class="n mono">${m.total}</td></tr>
    </tbody></table></div>
    ${m.note ? `<p class="muted small">${m.note}</p>` : ""}
    <footer>${m.cols.map(c => `<div>${c.map(esc).join("<br>")}</div>`).join("") || `<div>Eigene Daten unter „Angebotsdaten“ eintragen</div>`}</footer>`;
}
function cxQuoteText() {
  const m = CX.quoteModel; if (!m) return "";
  return `Angebot ${m.no} vom ${m.date}\n\n${m.cust.join("\n")}\n\n${m.title} – ${m.sub}\nMenge: ${m.qty} Stk\nEinzelpreis: ${m.unit}\nGesamt: ${m.total}\n${m.note || `inkl. ${CX.cfg.settings.vat} % MwSt`}\nGültig bis ${m.valid}\n\n${m.cols.slice(0, 2).flat().join("\n")}`;
}
async function cxNextNo() {
  const r = await api("/api/calc/quote-no", { method: "POST" });
  CX.cfg.settings.next_no = r.next; $("#cqNo").value = r.no; store.set("cqNo", r.no); cxRenderResult();
}

/* ---------- Drucker, Profile, Einstellungen ---------- */
function cxRenderCosts() {
  $("#cxPrinters").innerHTML = CX.printers.map((p, i) => `<tr><td>${esc(p.name)} <span class="pill">${{ bambu: "Bambu-Konto", manual: "manuell", default: "Standard" }[p.source]}</span></td>
    ${["price", "life", "watt", "wear"].map(k => `<td class="n"><input type="number" data-pk="${esc(p.key)}" data-k="${k}" value="${p[k]}" step="${k === "wear" ? 0.01 : 1}" min="0" class="cx-num"></td>`).join("")}
    <td class="n mono" data-ph="${esc(p.key)}">${cxMoney((+p.price || 0) / Math.max(1, +p.life || 1) + (+p.wear || 0))}</td>
    <td class="n">${p.source === "manual" ? `<button type="button" class="ghost mini" data-pdel="${esc(p.key)}" aria-label="${esc(p.name)} löschen">✕</button>` : ""}</td></tr>`).join("")
    + (CX.printers.length === 1 && CX.printers[0].source === "default" ? `<tr><td colspan="7" class="muted small">Noch keine Drucker. Verbinde dein Bambu-Konto unter „Drucker → Einrichten“ oder lege unten einen Drucker an – bis dahin rechnet der Standarddrucker mit der Ø Leistung aus den Einstellungen.</td></tr>` : "");
  $("#cxProfiles").innerHTML = CX.cfg.profiles.map((p, i) => `<tr><td>${esc(p.name)}</td>
    ${["margin", "rate", "risk"].map(k => `<td class="n"><input type="number" data-pr="${i}" data-k="${k}" value="${p[k]}" step="1" min="0" class="cx-num"></td>`).join("")}</tr>`).join("");
  const st = CX.cfg.settings;
  $("#csKwh").value = CX.kwh; $("#csVat").value = st.vat; $("#csKlein").checked = !!st.klein;
  $("#csCur").innerHTML = CX_CURRENCIES.map(([c, n]) => `<option value="${c}" ${c === cxCur() ? "selected" : ""}>${c} – ${n}</option>`).join("");
  $("#csRound").innerHTML = [["none", "keine"], ["0.10", "auf " + cxMoney(0.1)], ["0.50", "auf " + cxMoney(0.5)], ["0.99", "auf ,99"]]
    .map(([v, n]) => `<option value="${v}" ${v === st.round ? "selected" : ""}>${n}</option>`).join("");
}
function cxRenderSender() {
  const sd = CX.cfg.sender;
  $("#csSender").innerHTML = CX_SENDER.map(([k, n]) => `<label>${n}<input data-sd="${k}" value="${esc(sd[k] || "")}"></label>`).join("");
  $("#csPrefix").value = CX.cfg.settings.prefix || ""; $("#csNext").value = CX.cfg.settings.next_no || 1; $("#csValid").value = CX.cfg.settings.valid || 14;
  $("#csLogoPrev").innerHTML = CX.cfg.logo ? `<img src="${CX.cfg.logo}" alt="Eigenes Logo">` : `<svg width="48" height="48" viewBox="0 0 64 64" aria-hidden="true"><use href="#psLogo"/></svg>`;
  $("#csLogoMeta").textContent = CX.cfg.logo ? "Eigenes Logo aktiv" : "Standard: #Powerscripting-Logo";
  $("#csLogoDel").hidden = !CX.cfg.logo;
}

/* ---------- 3MF: Upload und Bibliothek ---------- */
function cxMatch(type, color) {
  const norm = s => String(s || "").toUpperCase().replace(/[\s_]+/g, "");
  const t = norm(type), hex = h => { h = String(h || "").replace("#", ""); return [0, 2, 4].map(i => parseInt(h.substr(i, 2), 16) || 0); }, c = hex(color);
  // Familie = erstes Wort der Materialangabe („PETG Basic“ → PETG, „PETG-CF“ bleibt PETG-CF), danach nach Farbe
  const fam = f => norm(String(f.material || "").trim().split(/\s+/)[0]);
  let cand = CX.fils.filter(f => fam(f) === t);
  if (!cand.length) cand = CX.fils.filter(f => norm(f.material).startsWith(t) || t.startsWith(fam(f)));
  if (!cand.length) return CX.fils[0] ? CX.fils[0].id : null;
  const dist = f => hex(f.color).reduce((s, v, i) => s + (v - c[i]) ** 2, 0) + (f.stock_g > 0 ? 0 : 1e6);
  return cand.sort((a, b) => dist(a) - dist(b))[0].id;
}
function cxPlatesFrom(list) {
  return list.filter(p => (p.seconds || 0) > 0 || (p.filaments || []).length).map((p, i) => ({
    n: p.index || i + 1, hours: +((p.seconds || 0) / 3600).toFixed(2), ppp: Math.max(1, p.objects || 1), purge: 0,
    lines: (p.filaments && p.filaments.some(f => +f.g > 0) ? p.filaments : (+p.grams > 0 ? [{ ...((p.filaments || [])[0] || { id: "1" }), g: +p.grams }] : p.filaments || []))
      .map((f, k) => ({ slot: "#" + (f.id || k + 1), type: f.type, color: (f.color || "#888888").slice(0, 7), grams: +(+f.g || 0).toFixed(2), fil: cxMatch(f.type, f.color) })),
  }));
}
function cxUseJob(plates, file, meta, source, title) {
  const keep = CX.job || cxNewJob();
  CX.job = { ...keep, file, meta, source, title: title || "", plates, plate: 0, scope: "all" };
  if (title) { $("#cqTitle").value = title; store.set("cqTitle", title); }
  cxSaveJob(); setTab("calc"); cxSetSub("calc");
}
/* 3MF lesen: 1. slice_info.config (Bambu Studio / OrcaSlicer, geslict)
               2. Kopf von Metadata/plate_N.gcode (falls slice_info fehlt oder nicht lesbar)
               3. Projektdatei ohne Slicing: Platten + Filamente übernehmen, Zeit/Gramm von Hand */
const CX_META = n => n === "Metadata/slice_info.config" || n === "Metadata/model_settings.config" || n === "Metadata/project_settings.config";
function cxAttr(tag, name) { const m = tag.match(new RegExp(`\\b${name}="([^"]*)"`)); return m ? m[1] : null; }
function cxSliceInfo(text) {
  // bewusst ohne DOMParser: ein einziges unmaskiertes Zeichen im Objektnamen machte sonst die ganze Datei unlesbar
  return [...text.matchAll(/<plate>([\s\S]*?)<\/plate>/g)].map((m, i) => {
    const body = m[1], meta = {};
    for (const t of body.matchAll(/<metadata\b[^>]*>/g)) { const k = cxAttr(t[0], "key"); if (k) meta[k] = cxAttr(t[0], "value"); }
    let fil = [...body.matchAll(/<filament\b[^>]*>/g)].map(t => ({ id: cxAttr(t[0], "id"), type: cxAttr(t[0], "type"), color: cxAttr(t[0], "color"),
      g: +(cxAttr(t[0], "used_g") || cxAttr(t[0], "usedG")) || 0 }));
    // keine Gramm je Filament, aber Gesamtgewicht der Platte → auf das erste Filament
    if (!fil.some(f => f.g > 0) && +meta.weight > 0) fil = [{ ...(fil[0] || { id: "1", type: "", color: "#888888" }), g: +meta.weight }];
    return { index: +(meta.index || i + 1), seconds: Math.round(+meta.prediction || 0), objects: (body.match(/<object\b/g) || []).length, filaments: fil };
  });
}
function cxGcodeHead(text, index, proj) {
  const hms = s => { let t = 0; for (const [, v, u] of String(s).matchAll(/(\d+(?:\.\d+)?)\s*([dhms])/g)) t += +v * { d: 86400, h: 3600, m: 60, s: 1 }[u]; return t; };
  const tm = text.match(/;\s*total estimated time\s*[:=]\s*([^;\n]+)/i) || text.match(/;\s*(?:model printing time|estimated printing time \(normal mode\))\s*[:=]\s*([^;\n]+)/i);
  // Bambu Studio: „; total filament weight [g] : 23.43,8.70“ + „; filament: 1,4“ (genutzte Filament-Nummern)
  const w = (text.match(/;\s*total filament weight \[g\]\s*:\s*([^\n]+)/i) || text.match(/;\s*filament used \[g\]\s*=\s*([^\n]+)/i) || [])[1];
  const grams = w ? w.split(/[,;]/).map(x => +x || 0) : [];
  const ids = ((text.match(/;\s*filament\s*:\s*([\d,\s]+)\n/i) || [])[1] || "").split(",").map(x => +x).filter(Boolean);
  const types = proj.filament_type || [], cols = proj.filament_colour || [];
  return { index, seconds: Math.round(tm ? hms(tm[1]) : 0), objects: 0,
    filaments: grams.map((g, k) => { const id = ids.length === grams.length ? ids[k] : k + 1;
      return { id: String(id), type: types[id - 1] || "", color: cols[id - 1] || "#888888", g }; }).filter(f => f.g > 0) };
}
async function cxRead3mf(buf) {
  if (typeof fflate === "undefined") await libScript("/static/vendor/three/fflate.min.js");
  const u8 = new Uint8Array(buf);
  const meta = fflate.unzipSync(u8, { filter: f => CX_META(f.name) });
  const txt = n => meta[n] ? fflate.strFromU8(meta[n]) : "";
  let proj = {}; try { proj = JSON.parse(txt("Metadata/project_settings.config") || "{}"); } catch { /* ältere Formate */ }
  let list = txt("Metadata/slice_info.config") ? cxSliceInfo(txt("Metadata/slice_info.config")) : [];
  if (!list.some(p => p.seconds > 0)) {
    // G-Code-Kopf lesen – nur die ersten 64 KB jeder Platte entpacken wäre ideal, unzipSync entpackt ganz; deshalb einzeln
    const names = [];
    fflate.unzipSync(u8, { filter: f => { if (/^Metadata\/plate_\d+\.gcode$/.test(f.name)) names.push(f.name); return false; } });
    const fromG = [];
    for (const n of names) {
      const g = fflate.unzipSync(u8, { filter: f => f.name === n })[n];
      const head = fflate.strFromU8(g.subarray(0, 65536)) + "\n" + fflate.strFromU8(g.subarray(Math.max(0, g.length - 65536)));
      fromG.push(cxGcodeHead(head, +n.match(/plate_(\d+)/)[1], proj));
    }
    if (fromG.some(p => p.seconds > 0)) list = fromG;
  }
  if (list.some(p => p.seconds > 0)) return { list: list.filter(p => p.seconds > 0 || p.filaments.length), sliced: true };
  // MakerWorld-Datei? Dann stehen Zeit und Gramm im Druckprofil (Modell muss in der Bibliothek sein)
  const head = fflate.unzipSync(u8, { filter: f => /^3D\/3dmodel\.model$/i.test(f.name) });
  const mtxt = Object.values(head)[0] ? fflate.strFromU8(Object.values(head)[0].subarray(0, 200000)) : "";
  const mdv = k => (mtxt.match(new RegExp(`<metadata name="${k}"[^>]*>([^<]*)<`)) || [])[1] || "";
  const mwModel = mdv("DesignModelId"), mwProfile = mdv("DesignProfileId");
  if (mwModel || mwProfile) {
    try {
      const r = await api(`/api/makerworld/plates-for-file?model_id=${encodeURIComponent(mwModel)}&profile_id=${encodeURIComponent(mwProfile)}`);
      const mw = (r.plates || []).filter(p => p.seconds);
      if (mw.length) return { list: mw, sliced: true, source: "makerworld" };
    } catch { /* nicht in der Bibliothek → von Hand */ }
  }
  // Projekt ohne Slicing: Platten aus model_settings.config, Filamente aus den Projekteinstellungen
  const ms = txt("Metadata/model_settings.config");
  const ids = ms ? [...ms.matchAll(/<plate>([\s\S]*?)<\/plate>/g)].map((m, i) => {
    const id = [...m[1].matchAll(/<metadata\b[^>]*>/g)].map(t => t[0]).find(t => cxAttr(t, "key") === "plater_id");
    return { index: +(id ? cxAttr(id, "value") : i + 1), objects: (m[1].match(/<model_instance>/g) || []).length };
  }) : [];
  const fil = (proj.filament_type || []).map((t, k) => ({ id: String(k + 1), type: t, color: (proj.filament_colour || [])[k] || "#888888", g: 0 }));
  // welche Filamente eine Platte nutzt, steht erst nach dem Slicen fest → erstes Projektfilament als Vorschlag
  const plates = (ids.length ? ids : [{ index: 1, objects: 0 }]).map(p => ({ ...p, seconds: 0, filaments: fil.slice(0, 1) }));
  return { list: plates, sliced: false, hasModel: !!ms || fil.length > 0, mw: !!(mwModel || mwProfile) };
}
async function cxImportFile(file) {
  try {
    const r = await cxRead3mf(await file.arrayBuffer());
    const title = file.name.replace(/(\.gcode)?\.3mf$/i, "").replace(/[_-]+/g, " ");
    if (!r.list.length || (!r.sliced && !r.hasModel)) return toast("Keine 3MF von Bambu Studio / OrcaSlicer – Werte bitte von Hand eintragen");
    const plates = r.sliced ? cxPlatesFrom(r.list) : cxPlatesFrom(r.list.map(p => ({ ...p, filaments: p.filaments.length ? p.filaments : [{ id: "1", type: "", color: "#888888", g: 0 }] })))
      .map(p => ({ ...p, lines: p.lines.map(l => ({ ...l, grams: l.grams || 0 })) }));
    const n = `${plates.length} ${plates.length === 1 ? "Druckplatte" : "Druckplatten"}`;
    cxUseJob(plates, file.name, r.source === "makerworld" ? `${n} · Zeiten und Gramm aus dem MakerWorld-Druckprofil` : r.sliced ? `${n} · Filament automatisch zugeordnet, bitte prüfen`
      : r.mw ? `${n} · MakerWorld-Datei ohne Slice-Daten – Modell in die Bibliothek übernehmen, dann kommen Zeit und Gramm aus dem Druckprofil`
      : `${n} · nicht geslict – Druckzeit und Gramm je Platte eintragen (oder in Bambu Studio „Platte slicen“ und als .gcode.3mf exportieren)`, r.source || "upload", title);
    toast(r.source === "makerworld" ? "Werte aus dem MakerWorld-Druckprofil übernommen" : r.sliced ? "3MF importiert" : "Projekt ohne Slice-Daten übernommen – Zeit und Gramm bitte eintragen");
  } catch (e) { toast("Datei konnte nicht gelesen werden: " + e.message); }
}
async function cxFromLibraryFile(model, file) {
  if (!CX.cfg) await cxLoad();
  let plates = cxPlatesFrom(((file.meta && file.meta.plates) || []).filter(p => p.seconds));
  if (!plates.length && model.mw_design_id) {
    // MakerWorld-Projektdateien sind nicht geslict – Bambu nennt Zeit und Gramm je Platte aber im Druckprofil
    let mw = (model.mw_plates || []).filter(p => p.seconds);
    if (!mw.length) { try { mw = ((await api(`/api/makerworld/plates/${model.id}`)).plates || []).filter(p => p.seconds); } catch { mw = []; } }
    if (mw.length) {
      plates = cxPlatesFrom(mw);
      cxUseJob(plates, file.name, `${model.title} · ${plates.length} ${plates.length === 1 ? "Druckplatte" : "Druckplatten"} · Zeiten und Gramm aus dem MakerWorld-Druckprofil`, "makerworld", model.title);
      return toast("Werte aus dem MakerWorld-Druckprofil übernommen");
    }
  }
  if (!plates.length) {
    if (file.analyzing) return toast("Datei wird noch ausgewertet – gleich nochmal versuchen");
    // nicht geslict laut Analyse → Datei selbst lesen (G-Code-Kopf bzw. Projekt ohne Slice-Daten)
    const res = await fetch(`/api/library/files/${file.id}/${encodeURIComponent(file.name)}`);
    if (!res.ok) return toast("Datei konnte nicht geladen werden");
    const blob = await res.blob();
    return cxImportFile(new File([blob], file.name));
  }
  cxUseJob(plates, file.name, `${model.title} · ${plates.length} ${plates.length === 1 ? "Druckplatte" : "Druckplatten"} · aus der Bibliothek`, "library", model.title);
  toast("In die Kalkulation übernommen");
}
async function cxOpenLib() {
  $("#cxLibDlg").showModal(); CX.libSel = null; $("#cxLibQ").value = "";
  CX.libModels = (await api("/api/library/models?sort=updated")).filter(m => (m.kinds || []).includes("3mf"));
  cxRenderLib();
}
function cxRenderLib() {
  if (CX.libSel) {
    const m = CX.libSel, fl = m.file_list.filter(f => f.kind === "3mf");
    $("#cxLibList").innerHTML = `<button type="button" class="ghost mini" data-libback>← zurück</button><h3>${esc(m.title)}</h3>` + (fl.map(f => {
      const pl = ((f.meta && f.meta.plates) || []).filter(p => p.seconds);
      return `<button type="button" class="cx-libitem" data-libfile="${f.id}" ${f.analyzing ? "disabled" : ""}>
        ${f.thumb ? `<img src="${esc(f.thumb)}" alt="" loading="lazy">` : `<span class="cx-libph">3MF</span>`}
        <span><b>${esc(f.name)}</b><small class="muted">${pl.length ? `${pl.length} ${pl.length === 1 ? "Platte" : "Platten"} · ${cxNum(f.seconds / 3600, 1)} h · ${cxNum(f.grams, 0)} g` : f.analyzing ? "wird ausgewertet …" : m.mw_design_id ? "Zeiten aus dem MakerWorld-Druckprofil" : "nicht geslict – Zeit und Gramm von Hand"}</small></span></button>`;
    }).join("") || `<p class="muted">Keine 3MF-Datei in diesem Modell.</p>`);
    return;
  }
  const q = $("#cxLibQ").value.trim().toLowerCase(), list = (CX.libModels || []).filter(m => !q || m.title.toLowerCase().includes(q) || (m.tags || []).some(t => t.includes(q)));
  $("#cxLibList").innerHTML = list.map(m => `<button type="button" class="cx-libitem" data-libmodel="${m.id}">
      ${m.cover ? `<img src="${esc(m.cover)}" alt="" loading="lazy">` : `<span class="cx-libph">3MF</span>`}
      <span><b>${esc(m.title)}</b><small class="muted">${esc(m.creator || "")}${m.tags.length ? " · #" + m.tags.slice(0, 3).map(esc).join(" #") : ""}</small></span></button>`).join("")
    || `<p class="muted">Keine Modelle mit 3MF-Datei gefunden.</p>`;
}

/* ---------- PDF ---------- */
async function cxFontB64(url) {
  const buf = new Uint8Array(await (await fetch(url)).arrayBuffer()); let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return btoa(bin);
}
function cxImg(src) { return new Promise((ok, fail) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => fail(new Error("Logo konnte nicht geladen werden")); im.src = src; }); }
async function cxLogoPng(dataUrl) {
  const im = await cxImg(dataUrl), w = im.naturalWidth || 600, h = im.naturalHeight || 200, s = Math.min(1, 800 / Math.max(w, h)) || 1;
  const c = document.createElement("canvas"); c.width = Math.round(w * s); c.height = Math.round(h * s);
  c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
  return { data: c.toDataURL("image/png"), ratio: c.width / c.height };
}
async function cxDefaultLogo() {
  try { await document.fonts.load("italic 700 21px 'Chakra Petch'"); } catch {}
  const S = 4, c = document.createElement("canvas"); c.width = c.height = 64 * S; const x = c.getContext("2d"); x.scale(S, S);
  const g = x.createLinearGradient(0, 0, 64, 64); g.addColorStop(0, "#2fe29b"); g.addColorStop(1, "#36a9ff");
  const r = 14; x.beginPath(); x.moveTo(2 + r, 2); x.arcTo(62, 2, 62, 62, r); x.arcTo(62, 62, 2, 62, r); x.arcTo(2, 62, 2, 2, r); x.arcTo(2, 2, 62, 2, r); x.closePath();
  x.fillStyle = "#0b1630"; x.fill(); x.lineWidth = 3; x.strokeStyle = g; x.stroke(); x.lineCap = "round"; x.lineJoin = "round";
  x.stroke(new Path2D("M15 20 L9 32 L15 44")); x.stroke(new Path2D("M49 20 L55 32 L49 44"));
  x.fillStyle = "#e5eefc"; x.font = "italic 700 21px 'Chakra Petch', sans-serif"; x.textAlign = "center"; x.fillText("#PS", 32, 40);
  x.fillStyle = g; x.fill(new Path2D("M37 9 L30 22 L35 22 L31 31 L41 17 L36 17 L39 9 Z"));
  return c.toDataURL("image/png");
}
async function cxPdf() {
  const m = CX.quoteModel; if (!m) return;
  if (!window.jspdf) await libScript("/static/vendor/jspdf/jspdf.umd.min.js");
  const doc = new window.jspdf.jsPDF({ unit: "mm", format: "a4" });
  doc.addFileToVFS("Plex-R.ttf", await cxFontB64("/static/fonts/IBMPlexSans-Regular.ttf")); doc.addFont("Plex-R.ttf", "Plex", "normal");
  doc.addFileToVFS("Plex-B.ttf", await cxFontB64("/static/fonts/IBMPlexSans-Bold.ttf")); doc.addFont("Plex-B.ttf", "Plex", "bold");
  const INK = [12, 25, 48], MUTED = [83, 103, 138], LINE = [210, 220, 234], GREEN = [47, 226, 155], BLUE = [54, 169, 255];
  const L = 20, Rt = 190, W = Rt - L, font = (st, sz, col = INK) => { doc.setFont("Plex", st); doc.setFontSize(sz); doc.setTextColor(...col); };
  const rule = (x1, y, x2, h) => { for (let i = 0; i < 60; i++) { const k = i / 59; doc.setFillColor(...GREEN.map((v, j) => Math.round(v + (BLUE[j] - v) * k))); doc.rect(x1 + i * (x2 - x1) / 60, y, (x2 - x1) / 60 + 0.05, h, "F"); } };
  let y = 18;
  if (m.logo) { const { data, ratio } = await cxLogoPng(m.logo); let h = 18, w = h * ratio; if (w > 60) { w = 60; h = w / ratio; } doc.addImage(data, "PNG", L, y, w, h, undefined, "FAST"); }
  else { doc.addImage(await cxDefaultLogo(), "PNG", L, y, 16, 16, undefined, "FAST"); font("bold", 13); doc.text("POWERSCRIPTING", L + 20, y + 7.5); font("normal", 8.5, MUTED); doc.text("Elevate. Automate. Innovate.", L + 20, y + 12.5); }
  font("normal", 9, MUTED); doc.text(m.labels.quote, Rt, y + 3, { align: "right" }); font("bold", 11); doc.text(m.no, Rt, y + 8.5, { align: "right" });
  font("normal", 9, MUTED); doc.text([m.labels.date, m.labels.valid], Rt, y + 13.5, { align: "right", lineHeightFactor: 1.35 });
  rule(L, 40, Rt, 0.8);
  y = 52;
  if (m.sendLine) { font("normal", 7.5, MUTED); doc.text(m.sendLine, L, y); doc.setDrawColor(...LINE); doc.setLineWidth(0.2); doc.line(L, y + 1.2, L + Math.min(85, doc.getTextWidth(m.sendLine)), y + 1.2); }
  y += 6; m.cust.forEach((line, i) => { font(i === 0 ? "bold" : "normal", 10.5); doc.text(line, L, y); y += 5; });
  if (m.mail) { font("normal", 9, MUTED); doc.text(m.mail, L, y); y += 5; }
  y = Math.max(y + 10, 92); font("bold", 16); doc.text(doc.splitTextToSize(m.title, W), L, y); y += 6;
  font("normal", 9.5, MUTED); const sub = doc.splitTextToSize(m.sub, W); doc.text(sub, L, y); y += sub.length * 4.5 + 6;
  const cx = { pos: L, desc: L + 12, qty: 128, unit: 158, total: Rt };
  font("bold", 8.5, MUTED);
  doc.text(m.labels.pos.toUpperCase(), cx.pos, y); doc.text(m.labels.desc.toUpperCase(), cx.desc, y);
  doc.text(m.labels.qty.toUpperCase(), cx.qty, y, { align: "right" }); doc.text(m.labels.unit.toUpperCase(), cx.unit, y, { align: "right" }); doc.text(m.labels.total.toUpperCase(), cx.total, y, { align: "right" });
  y += 2.5; doc.setDrawColor(...LINE); doc.setLineWidth(0.3); doc.line(L, y, Rt, y); y += 6;
  font("normal", 10); doc.text("1", cx.pos, y);
  const tl = doc.splitTextToSize(m.title, cx.qty - cx.desc - 18); font("bold", 10); doc.text(tl, cx.desc, y);
  font("normal", 10); doc.text(String(m.qty), cx.qty, y, { align: "right" }); doc.text(m.unit, cx.unit, y, { align: "right" }); doc.text(m.total, cx.total, y, { align: "right" });
  y += tl.length * 4.6; font("normal", 8.5, MUTED); const dl = doc.splitTextToSize(m.desc, cx.qty - cx.desc - 18); doc.text(dl, cx.desc, y); y += dl.length * 4 + 3;
  doc.setDrawColor(...LINE); doc.line(L, y, Rt, y); y += 6;
  if (m.vatLine) { font("normal", 9, MUTED); doc.text(m.vatLine, cx.desc, y); doc.text(m.vatAmount, cx.total, y, { align: "right" }); y += 6; }
  rule(cx.unit - 30, y - 3.5, Rt, 0.5); font("bold", 11.5); doc.text(m.labels.sum, cx.desc, y + 2); doc.text(m.total, cx.total, y + 2, { align: "right" }); y += 12;
  if (m.note) { font("normal", 9, MUTED); doc.text(doc.splitTextToSize(m.note, W), L, y); }
  if (m.cols.length) { const fy = 272, cw = W / m.cols.length; doc.setDrawColor(...LINE); doc.setLineWidth(0.2); doc.line(L, fy - 5, Rt, fy - 5); font("normal", 7.5, MUTED); m.cols.forEach((c, i) => doc.text(c, L + i * cw, fy, { lineHeightFactor: 1.4, maxWidth: cw - 4 })); }
  doc.setProperties({ title: `${m.labels.quote} ${m.no}`, subject: m.title, creator: "3D Print Manager" });
  doc.save(`Angebot_${m.no}`.replace(/[^\w.\-äöüÄÖÜß]+/g, "_") + ".pdf");
}

/* ---------- Ereignisse ---------- */
const cxTab = $("#tab-calc");
["cqCust", "cqContact", "cqMail", "cqStreet", "cqZip", "cqCity", "cqTitle", "cqNo"].forEach(id => { const v = store.get(id, null); if (v != null) $("#" + id).value = v; });
cxTab.addEventListener("input", e => {
  const el = e.target, v = parseFloat(el.value), n = isFinite(v) ? v : 0;
  if (!CX.job) return;
  const p = cxPlate(), j = CX.job, c = CX.cfg;
  if (el.id === "cxH") p.hours = n; else if (el.id === "cxPpp") p.ppp = Math.max(1, Math.round(n)); else if (el.id === "cxPurge") p.purge = n;
  else if (el.id === "cxQty") j.qty = Math.max(1, Math.round(n)); else if (el.id === "cxPrep") j.prep = n; else if (el.id === "cxPost") j.post = n;
  else if (el.dataset.grams !== undefined) { p.lines[+el.dataset.grams].grams = n; const cell = $(`[data-lcost="${el.dataset.grams}"]`); if (cell) cell.textContent = cxMoney(n * cxPerKg(p.lines[+el.dataset.grams].fil) / 1000); }
  else if (el.dataset.xn !== undefined) j.extras[+el.dataset.xn].name = el.value;
  else if (el.dataset.xp !== undefined) j.extras[+el.dataset.xp].price = n;
  else if (el.dataset.xc !== undefined) j.extras[+el.dataset.xc].n = n;
  else if (el.dataset.pk !== undefined) {
    const P = CX.printers.find(x => x.key === el.dataset.pk); P[el.dataset.k] = n;
    if (P.source !== "manual") c.printer_costs[P.key] = { price: P.price, life: P.life, watt: P.watt, wear: P.wear };
    else { const mp = c.manual_printers.find(x => x.key === P.key); if (mp) mp[el.dataset.k] = n; }
    $(`[data-ph="${P.key}"]`).textContent = cxMoney((+P.price || 0) / Math.max(1, +P.life || 1) + (+P.wear || 0)); cxSaveCfg();
  }
  else if (el.dataset.pr !== undefined) { c.profiles[+el.dataset.pr][el.dataset.k] = n; cxSaveCfg(); }
  else if (el.dataset.sd !== undefined) { c.sender[el.dataset.sd] = el.value; cxSaveCfg(); }
  else if (el.id === "csVat") { c.settings.vat = n; cxSaveCfg(); }
  else if (el.id === "csPrefix") { c.settings.prefix = el.value; cxSaveCfg(); }
  else if (el.id === "csNext") { c.settings.next_no = Math.max(1, Math.round(n)); cxSaveCfg(); }
  else if (el.id === "csValid") { c.settings.valid = Math.max(1, Math.round(n)); cxSaveCfg(); }
  else if (el.id === "csKwh") {
    CX.kwh = n; clearTimeout(cxTab._kwh);
    cxTab._kwh = setTimeout(() => api("/api/settings", { method: "PUT", body: JSON.stringify({ kwh_price: n }) }).then(s => { state.settings = s; }).catch(err => toast("Speichern fehlgeschlagen: " + err.message)), 500);
  }
  else if (el.id && el.id.startsWith("cq")) { store.set(el.id, el.value); }
  else return;
  if (el.id === "cxH") {
    const b = $(`#cxPlates [data-plate="${j.plate}"]`); if (b) b.textContent = `Platte ${p.n} · ${cxNum(p.hours)} h`;
    const a = $("#cxPlates [data-scope=all]"); if (a) a.textContent = `Komplett · ${j.plates.length} Platten · ${cxNum(j.plates.reduce((s, x) => s + (+x.hours || 0), 0))} h`;
  }
  cxSaveJob(); cxRenderResult();
});
cxTab.addEventListener("change", e => {
  const el = e.target; if (!CX.job) return;
  const c = CX.cfg;
  if (el.id === "cxPrinter") { CX.job.printer = el.value; cxSaveCfg(); }
  else if (el.id === "cxProfile") { CX.job.profile = el.value; cxSaveCfg(); }
  else if (el.dataset.line !== undefined) { cxPlate().lines[+el.dataset.line].fil = +el.value; cxSaveJob(); return cxRenderCalc(); }
  else if (el.id === "csCur") { c.settings.cur = el.value; cxSaveCfg(); cxRenderCosts(); }
  else if (el.id === "csRound") { c.settings.round = el.value; cxSaveCfg(); }
  else if (el.id === "csKlein") { c.settings.klein = el.checked; cxSaveCfg(); }
  else if (el.id === "cx3mf" && el.files[0]) { cxImportFile(el.files[0]); el.value = ""; return; }
  else if (el.id === "csLogo" && el.files[0]) {
    const f = el.files[0]; el.value = "";
    if (f.size > 500 * 1024) return toast("Logo ist größer als 500 KB – bitte verkleinern");
    const rd = new FileReader(); rd.onload = () => { c.logo = rd.result; cxSaveCfg(); cxRenderSender(); cxRenderResult(); toast("Logo übernommen"); }; rd.readAsDataURL(f); return;
  }
  else return;
  cxSaveJob(); cxRenderResult();
});
cxTab.addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b || !CX.job) return;
  const j = CX.job, c = CX.cfg;
  if (b.dataset.cx) return cxSetSub(b.dataset.cx);
  if (b.dataset.plate !== undefined) { j.plate = +b.dataset.plate; cxSaveJob(); return cxRenderCalc(); }
  if (b.dataset.scope) { j.scope = b.dataset.scope; cxSaveJob(); return cxRenderCalc(); }
  if (b.dataset.ldel !== undefined) { cxPlate().lines.splice(+b.dataset.ldel, 1); }
  else if (b.dataset.xdel !== undefined) { j.extras.splice(+b.dataset.xdel, 1); }
  else if (b.id === "cxAddLine") { const p = cxPlate(); p.lines.push({ slot: "#" + (p.lines.length + 1), grams: 20, fil: CX.fils[0] ? CX.fils[0].id : null, manual: true }); }
  else if (b.id === "cxAddPlate") { const n = Math.max(0, ...j.plates.map(x => x.n)) + 1; j.plates.push({ n, hours: 1, ppp: 1, purge: 0, lines: [{ slot: "#1", grams: 20, fil: CX.fils[0] ? CX.fils[0].id : null, manual: true }] }); j.plate = j.plates.length - 1; }
  else if (b.id === "cxDelPlate") { if (j.plates.length < 2) return; const [x] = j.plates.splice(j.plate, 1); j.plate = Math.min(j.plate, j.plates.length - 1); toast(`Platte ${x.n} entfernt`); }
  else if (b.id === "cxAddExtra") { j.extras.push({ name: "Neues Zubehör", price: 0.1, n: 1 }); }
  else if (b.id === "cxNew") { CX.job = cxNewJob(); toast("Neues Projekt – Werte eintragen"); }
  else if (b.id === "cxFromLib") { return cxOpenLib().catch(err => toast("Bibliothek: " + err.message)); }
  else if (b.id === "cxToQuote") { if (!cxVal("#cqNo")) cxNextNo().catch(() => {}); return cxSetSub("quote"); }
  else if (b.id === "cqNewNo") { return cxNextNo().catch(err => toast("Nummer: " + err.message)); }
  else if (b.id === "cqPdf") { b.disabled = true; return cxPdf().then(() => toast("PDF gespeichert")).catch(err => toast("PDF konnte nicht erstellt werden: " + err.message)).finally(() => b.disabled = false); }
  else if (b.id === "cqCopy") { return navigator.clipboard.writeText(cxQuoteText()).then(() => toast("Angebotstext kopiert"), () => toast("Kopieren nicht möglich")); }
  else if (b.dataset.pdel !== undefined) { c.manual_printers = c.manual_printers.filter(x => x.key !== b.dataset.pdel); CX.printers = CX.printers.filter(x => x.key !== b.dataset.pdel); if (j.printer === b.dataset.pdel) j.printer = CX.printers[0] && CX.printers[0].key; cxSaveCfg(); cxRenderCosts(); }
  else if (b.id === "csLogoDel") { c.logo = null; cxSaveCfg(); cxRenderSender(); }
  else return;
  cxSaveJob(); if (CX.sub === "calc") cxRenderCalc(); else cxRenderResult();
});
$("#cxAddPrinter").addEventListener("submit", e => {
  e.preventDefault();
  const name = cxVal("#npName"); if (!name) return;
  const P = { key: "m" + Date.now().toString(36), name, price: +$("#npPrice").value || 0, life: Math.max(1, +$("#npLife").value || 1), watt: +$("#npWatt").value || 0, wear: +$("#npWear").value || 0 };
  CX.cfg.manual_printers.push(P); CX.printers = CX.printers.filter(x => x.source !== "default"); CX.printers.push({ ...P, source: "manual" }); $("#npName").value = "";
  if (!CX.job.printer || CX.job.printer === "default") CX.job.printer = P.key;
  cxSaveCfg(); cxRenderCosts(); toast(name + " hinzugefügt");
});
$("#cxLibDlg").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.libback !== undefined) { CX.libSel = null; return cxRenderLib(); }
  if (b.dataset.libmodel) { CX.libSel = await api(`/api/library/models/${b.dataset.libmodel}`); const fl = CX.libSel.file_list.filter(f => f.kind === "3mf");
    if (fl.length === 1 && ((fl[0].meta && (fl[0].meta.plates || []).some(p => p.seconds)) || CX.libSel.mw_design_id)) { $("#cxLibDlg").close(); return cxFromLibraryFile(CX.libSel, fl[0]).catch(err => toast("Kalkulation: " + err.message)); }
    return cxRenderLib(); }
  if (b.dataset.libfile) { const f = CX.libSel.file_list.find(x => x.id === +b.dataset.libfile); $("#cxLibDlg").close(); cxFromLibraryFile(CX.libSel, f).catch(err => toast("Kalkulation: " + err.message)); }
});
$("#cxLibQ").addEventListener("input", () => cxRenderLib());
const cxDrop = $("#cxDrop");
["dragover", "dragenter"].forEach(ev => cxDrop.addEventListener(ev, e => { e.preventDefault(); cxDrop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => cxDrop.addEventListener(ev, () => cxDrop.classList.remove("over")));
cxDrop.addEventListener("drop", e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f && CX.job) cxImportFile(f); });

function loadCalc() { return cxLoad(); }
if (state.tab === "calc") loadCalc().catch(e => toast("Kalkulation: " + e.message));
