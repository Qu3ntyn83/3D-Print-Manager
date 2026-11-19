/* Wartung der Drucker – Aufgaben je Modellreihe (Bambu-Wiki), fällig nach Zeit, Filament oder Druckstunden. */
const MT = { data: null, open: {} };
const MT_STATUS = { due: ["Fällig", "bad"], soon: ["Bald", "warn"], ok: ["OK", "ok"], off: ["Aus", ""] };

function mtIv(iv) {
  const p = [];
  const mo = iv.days / 30.4, m = Math.round(mo);
  if (iv.days) p.push(iv.days === 7 ? "wöchentlich" : m >= 1 && Math.abs(mo - m) < 0.1 ? (m === 1 ? "monatlich" : `alle ${m} Monate`) : `alle ${iv.days} Tage`);
  if (iv.kg) p.push(`${cxNumMt(iv.kg)} kg Filament`);
  if (iv.kg_abrasive) p.push(`${cxNumMt(iv.kg_abrasive)} kg ${iv.kg ? "CF/GF" : "abrasiv"}`);
  if (iv.hours) p.push(`${cxNumMt(iv.hours)} h Druck`);
  return p.join(" · ") || "kein Intervall";
}
function cxNumMt(n) { return (+n).toLocaleString("de-DE", { maximumFractionDigits: 1 }); }

async function loadMaint() {
  MT.data = await api("/api/maintenance");
  renderMaint(); mtBadge();
}
function mtBadge() {
  const d = MT.data; if (!d) return;
  const b = $("#maintDue"); if (b) { b.textContent = d.due ? String(d.due) : ""; b.title = d.due ? `${d.due} Wartungen fällig` : ""; }
}
function mtTask(p, t) {
  const [lbl, cls] = MT_STATUS[t.status];
  const pct = Math.min(100, Math.round(t.progress * 100));
  const last = t.last_done ? `zuletzt ${fmtDay(t.last_done)}` : `gezählt ab ${fmtDay(t.counted_from)}`;
  const since = [t.since.days >= 1 ? `${Math.floor(t.since.days)} Tage` : "", t.since.kg ? `${cxNumMt(t.since.kg)} kg` : "", t.since.hours ? `${cxNumMt(t.since.hours)} h Druck` : ""].filter(Boolean).join(" · ");
  return `<li class="mt-task ${t.status}" data-p="${p.id}" data-k="${esc(t.key)}">
    <span class="pill ${cls}">${lbl}</span>
    <div class="mt-main">
      <b>${esc(t.name)}</b>
      <small class="muted">${esc(mtIv(t.interval))} · ${last}${since ? ` · seitdem ${since}` : ""}</small>
      ${t.hint ? `<small class="muted mt-hint">${esc(t.hint)}</small>` : ""}
    </div>
    ${t.status !== "off" ? `<div class="mt-due"><span class="mt-bar" role="img" aria-label="${pct} % des Intervalls"><i style="width:${pct}%"></i></span><small>${esc(t.due)}</small></div>` : `<div class="mt-due"></div>`}
    <div class="mt-acts">
      ${t.status !== "off" ? `<button type="button" class="${t.status === "ok" ? "ghost" : "primary"}" data-mt="done">Erledigt</button>` : ""}
      <button type="button" class="ghost" data-mt="edit" aria-label="${esc(t.name)} bearbeiten" title="Intervall, Datum, ein/aus">⋯</button>
    </div></li>`;
}
function renderMaint() {
  const el = $("#mtList"), d = MT.data;
  if (!d.printers.length) { el.innerHTML = `<div class="panel"><p class="muted">Noch kein Drucker verbunden – unter <b>Drucker → Einrichten</b> hinzufügen.</p></div>`; return; }
  el.innerHTML = d.printers.map(p => {
    const act = p.tasks.filter(t => t.status !== "off"), off = p.tasks.filter(t => t.status === "off");
    const head = p.due ? `<span class="pill bad">${p.due} fällig</span>` : p.soon ? `<span class="pill warn">${p.soon} bald</span>` : `<span class="pill ok">alles erledigt</span>`;
    return `<section class="panel mt-printer">
      <div class="row-head"><h3>${esc(p.name)}</h3><span class="muted">${esc(p.model || "")}</span>${head}<span class="spacer"></span>
        ${p.wiki ? `<a class="lnk" href="${esc(p.wiki)}" target="_blank" rel="noopener noreferrer">Bambu-Wiki ↗</a>` : ""}
        <button type="button" class="ghost" data-mtp="${p.id}" data-mt="log">Protokoll</button>
        <button type="button" class="ghost" data-mtp="${p.id}" data-mt="add">+ Eigene Aufgabe</button></div>
      <div class="mt-totals">
        <span><b>${cxNumMt(p.totals.hours)} h</b><small>Druckzeit</small></span>
        <span><b>${cxNumMt(p.totals.kg)} kg</b><small>Filament</small></span>
        <span><b>${p.totals.jobs}</b><small>Drucke${p.totals.since ? " seit " + fmtDay(p.totals.since) : ""}</small></span>
      </div>
      <ul class="mt-tasks">${act.map(t => mtTask(p, t)).join("")}</ul>
      ${off.length ? `<details class="mt-off" ${MT.open[p.id] ? "open" : ""} data-mtoff="${p.id}"><summary>${off.length} ausgeschaltet</summary><ul class="mt-tasks">${off.map(t => mtTask(p, t)).join("")}</ul></details>` : ""}
    </section>`;
  }).join("");
  $$("#mtList details[data-mtoff]").forEach(x => x.ontoggle = () => { MT.open[x.dataset.mtoff] = x.open; });
}
function mtFind(pid, key) {
  const p = MT.data.printers.find(x => x.id === +pid);
  return [p, p && p.tasks.find(t => t.key === key)];
}
function mtReplace(p) {
  const i = MT.data.printers.findIndex(x => x.id === p.id);
  MT.data.printers[i] = p;
  MT.data.due = MT.data.printers.reduce((a, x) => a + x.due, 0);
  MT.data.soon = MT.data.printers.reduce((a, x) => a + x.soon, 0);
  renderMaint(); mtBadge();
}
const mtDate = s => (s || "").slice(0, 10);
function mtOpenDlg(html, onSubmit) {
  const dlg = $("#mtDlg");
  $("#mtForm").innerHTML = html;
  $("#mtForm").onclick = null;
  $$("#mtForm [data-close]").forEach(x => { x.onclick = () => dlg.close(); });
  $("#mtForm").onsubmit = async e => {
    e.preventDefault();
    try { await onSubmit(new FormData($("#mtForm")), e.submitter); dlg.close(); } catch (err) { toast(err.message); }
  };
  dlg.showModal();
}
$("#mtList").addEventListener("click", async e => {
  const b = e.target.closest("[data-mt]"); if (!b) return;
  const row = b.closest(".mt-task"), pid = row ? row.dataset.p : b.dataset.mtp, key = row && row.dataset.k;
  const [p, t] = mtFind(pid, key);
  if (b.dataset.mt === "done") {
    mtOpenDlg(`<header class="dlg-head"><h2>${esc(t.name)}</h2><button type="button" class="x" data-close>✕</button></header>
      <p class="muted">${esc(p.name)} · ${esc(mtIv(t.interval))}</p>
      <label>Erledigt am<input type="date" name="date" value="${new Date().toISOString().slice(0, 10)}" max="${new Date().toISOString().slice(0, 10)}" required></label>
      <label>Notiz <span class="muted">(optional)</span><input name="note" maxlength="500" placeholder="z. B. Öl, Teil, Auffälligkeiten"></label>
      <div class="dlg-actions"><button type="submit" class="primary">Als erledigt eintragen</button></div>`,
      async fd => {
        const today = new Date().toISOString().slice(0, 10), d = fd.get("date");
        mtReplace(await api(`/api/maintenance/${p.id}/${encodeURIComponent(t.key)}/done`, { method: "POST",
          body: JSON.stringify({ date: d === today ? null : d + "T12:00:00", note: fd.get("note") }) }));
        toast(`${t.name}: erledigt`);
      });
  } else if (b.dataset.mt === "edit") {
    const iv = t.interval, dv = t.default_interval;
    mtOpenDlg(`<header class="dlg-head"><h2>${t.custom ? "Eigene Aufgabe" : esc(t.name)}</h2><button type="button" class="x" data-close>✕</button></header>
      ${t.custom ? `<label>Bezeichnung<input name="name" value="${esc(t.name)}" maxlength="120" required></label>` : `<p class="muted">Standard nach Bambu-Wiki: ${esc(mtIv(dv))}. Leer lassen = Standard, 0 = Kriterium aus.</p>`}
      <div class="mt-ivs">
        <label>Alle … Tage<input type="number" name="days" min="0" step="1" value="${iv.days ?? ""}" placeholder="${dv.days ?? "–"}"></label>
        <label>Alle … kg Filament<input type="number" name="kg" min="0" step="0.5" value="${iv.kg ?? ""}" placeholder="${dv.kg ?? "–"}"></label>
        <label>Alle … h Druck<input type="number" name="hours" min="0" step="1" value="${iv.hours ?? ""}" placeholder="${dv.hours ?? "–"}"></label>
      </div>
      <label class="chkline"><input type="checkbox" name="enabled" ${t.enabled ? "checked" : ""}> Aufgabe anzeigen und erinnern</label>
      <label>Zuletzt erledigt <span class="muted">(nachtragen, falls schon gemacht)</span><input type="date" name="last" value="${mtDate(t.last_done)}" max="${new Date().toISOString().slice(0, 10)}"></label>
      <div class="dlg-actions">${t.custom ? `<button type="submit" class="ghost danger" value="del">Löschen</button>` : ""}<span class="spacer"></span><button type="submit" class="primary" value="save">Speichern</button></div>`,
      async (fd, sub) => {
        const url = `/api/maintenance/${p.id}/${encodeURIComponent(t.key)}`;
        if (sub && sub.value === "del") {
          if (!confirm(`„${t.name}“ löschen?`)) throw new Error("abgebrochen");
          return mtReplace(await api(url, { method: "DELETE" }));
        }
        const body = { enabled: fd.get("enabled") === "on" };
        for (const k of ["days", "kg", "hours"]) {
          const v = fd.get(k);
          if (t.custom ? true : String(v) !== String(iv[k] ?? "")) body[k] = v === "" ? null : +v;
        }
        if (t.custom) body.name = fd.get("name");
        let r = await api(url, { method: "PUT", body: JSON.stringify(body) });
        const last = fd.get("last");
        if (last && last !== mtDate(t.last_done)) r = await api(url + "/done", { method: "POST", body: JSON.stringify({ date: last + "T12:00:00", note: "nachgetragen" }) });
        mtReplace(r);
      });
  } else if (b.dataset.mt === "add") {
    mtOpenDlg(`<header class="dlg-head"><h2>Eigene Wartungsaufgabe · ${esc(p.name)}</h2><button type="button" class="x" data-close>✕</button></header>
      <label>Bezeichnung<input name="name" maxlength="120" required placeholder="z. B. Druckplatte reinigen, Düse tauschen"></label>
      <div class="mt-ivs">
        <label>Alle … Tage<input type="number" name="days" min="0" step="1"></label>
        <label>Alle … kg Filament<input type="number" name="kg" min="0" step="0.5"></label>
        <label>Alle … h Druck<input type="number" name="hours" min="0" step="1"></label>
      </div>
      <p class="muted small">Mindestens ein Intervall – fällig ist die Aufgabe, sobald das erste erreicht ist.</p>
      <div class="dlg-actions"><button type="submit" class="primary">Anlegen</button></div>`,
      async fd => {
        const body = { name: fd.get("name") };
        for (const k of ["days", "kg", "hours"]) if (fd.get(k)) body[k] = +fd.get(k);
        mtReplace(await api(`/api/maintenance/${p.id}/custom`, { method: "POST", body: JSON.stringify(body) }));
      });
  } else if (b.dataset.mt === "log") {
    const log = await api(`/api/maintenance/${p.id}/log`);
    mtOpenDlg(`<header class="dlg-head"><h2>Wartungsprotokoll · ${esc(p.name)}</h2><button type="button" class="x" data-close>✕</button></header>
      ${log.length ? `<ul class="mt-log">${log.map(l => `<li data-l="${l.id}"><span>${fmtDay(l.done_at)}</span><b>${esc(l.name)}</b>${l.note ? `<small class="muted">${esc(l.note)}</small>` : ""}
        <button type="button" class="ghost mini" data-lrm="${l.id}" title="Eintrag löschen (versehentlich erledigt)">✕</button></li>`).join("")}</ul>` : `<p class="muted">Noch nichts erledigt.</p>`}`,
      async () => {});
    $("#mtForm").onclick = async ev => {
      const x = ev.target.closest("[data-lrm]"); if (!x) return;
      if (!confirm("Eintrag löschen? „Zuletzt erledigt“ springt auf den vorigen Eintrag zurück.")) return;
      await api(`/api/maintenance/log/${x.dataset.lrm}`, { method: "DELETE" });
      x.closest("li").remove(); await loadMaint();
    };
  }
});
// Fälligkeiten für das Abzeichen im Menü auch ohne Besuch der Seite
setTimeout(() => api("/api/maintenance").then(d => { MT.data = MT.data || d; mtBadge(); }).catch(() => {}), 1500);
