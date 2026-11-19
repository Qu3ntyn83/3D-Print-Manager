"""Wartung der Drucker: Aufgaben je Modellreihe, Fälligkeit nach Zeit, Filamentmenge und Druckstunden.

Intervalle nach den Wartungsempfehlungen im Bambu-Lab-Wiki (Stand Nov. 2026). Bambu nennt Intervalle in Monaten,
Wochen oder Rollen – „Rolle“ wird hier als 1 kg verbrauchtes Filament gezählt. Abrasives Filament (CF/GF) zählt bei
Aufgaben mit kürzerem Intervall für abrasives Material entsprechend stärker.

Gezählt wird aus der Druckhistorie (print_jobs): Laufzeit und Filament je Drucker seit der letzten Erledigung.
Ohne Erledigung zählt ab dem Tag, an dem die Aufgabe zum ersten Mal angezeigt wurde – damit nicht alles sofort
überfällig ist. Den Zeitpunkt kann man nachtragen.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from flask import Blueprint, abort, jsonify, request

from bambu import conn

bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")

WIKI = {
    "X1": "https://wiki.bambulab.com/en/x1/maintenance/basic-maintenance",
    "P1": "https://wiki.bambulab.com/en/p1/maintenance/p1p-maintenance",
    "A1": "https://wiki.bambulab.com/en/a1/maintenance/basic-maintenance",
    "A1M": "https://wiki.bambulab.com/en/a1-mini/maintenance/period-maintenance",
    "H2": "https://wiki.bambulab.com/en/h2/maintenance/period-maintenance",
    "H2S": "https://wiki.bambulab.com/en/h2s/maintenance/period-maintenance",
}

# key, Name, Art, Intervall {days, kg, hours, kg_abrasive}, Hinweis, standardmäßig an
T = lambda key, name, cat, iv, hint="", on=True: {"key": key, "name": name, "cat": cat, "iv": iv, "hint": hint, "on": on}  # noqa: E731
WEEKLY = "Wöchentliche Sichtkontrolle – standardmäßig aus, bei Bedarf einschalten."
CUTTER = T("cutter", "Filament-Schneidmesser prüfen", "Verschleiß", {"kg": 4, "kg_abrasive": 1.5},
           "Normales Filament alle 3–5 Rollen, PA-CF/PA-GF nach 1–2 Rollen.")

CATALOG = {
    "X1": [
        T("x_rods", "X-Achse: Carbonstangen prüfen und reinigen", "Reinigen", {"days": 30, "kg_abrasive": 5}, "Bei ABS/ASA alle 5 Rollen."),
        T("yz_rods", "Y-/Z-Linearstangen prüfen und reinigen", "Reinigen", {"days": 30, "kg_abrasive": 5}, "Bei ABS/ASA alle 5 Rollen."),
        T("yz_rust", "Y-/Z-Linearstangen: Rostschutz auftragen", "Schmieren", {"days": 91}),
        T("z_screw", "Z-Gewindespindeln reinigen und fetten", "Schmieren", {"days": 91}),
        CUTTER,
        T("carbon", "Aktivkohlefilter tauschen", "Verschleiß", {"days": 91}, "Bei rund 8 h Druck am Tag; im Dauerbetrieb monatlich."),
        T("ext_gear", "Extruderzahnrad prüfen und reinigen", "Prüfen", {"days": 7}, WEEKLY, False),
        T("fans", "Lüfter prüfen und reinigen", "Prüfen", {"days": 7}, WEEKLY, False),
    ],
    "P1": [
        T("x_rods", "X-Achse: Carbonstangen prüfen und reinigen", "Reinigen", {"days": 30}),
        T("yz_rods", "Y-/Z-Linearstangen prüfen und reinigen", "Reinigen", {"days": 30, "kg_abrasive": 5}, "Bei ABS/ASA alle 5 Rollen."),
        T("yz_rust", "Y-/Z-Linearstangen: Rostschutz auftragen", "Schmieren", {"days": 91}),
        T("z_screw", "Z-Gewindespindeln prüfen und fetten", "Schmieren", {"days": 91}),
        CUTTER,
        T("ptfe", "PTFE-Schläuche prüfen", "Verschleiß", {"kg": 10, "kg_abrasive": 5}, "Nach etwa 10 Rollen normalem bzw. 5 Rollen abrasivem Filament."),
        T("fans", "Hotend, Frontabdeckung und Lüfter prüfen", "Prüfen", {"days": 7}, WEEKLY, False),
    ],
    "A1": [
        T("x_rail", "X-Schiene reinigen und schmieren", "Schmieren", {"days": 30}),
        T("y_rail", "Y-Schiene reinigen und schmieren", "Schmieren", {"days": 30}),
        T("z_screw", "Gewindespindel reinigen und fetten", "Schmieren", {"days": 91}),
        T("idler", "X-/Y-Umlenkrollen prüfen", "Prüfen", {"days": 91}),
        T("hotend_heat", "Hotend-Heizeinheit prüfen", "Prüfen", {"days": 30}),
        T("cutter", "Filament-Schneidmesser prüfen", "Verschleiß", {"kg": 3}, "Alle 3 Rollen PLA/ABS/PETG."),
        T("ptfe", "PTFE-Schlauch tauschen", "Verschleiß", {"kg": 6, "kg_abrasive": 2}, "Alle 6 Rollen PLA, alle 2 Rollen Carbonfaser."),
        T("fans", "Bauteil- und Hotend-Lüfter reinigen", "Prüfen", {"days": 7}, WEEKLY, False),
    ],
    "H2": [
        T("x_axis", "X-Achse reinigen und ölen", "Schmieren", {"days": 30}),
        T("y_rods", "Y-Linearstangen reinigen und ölen", "Schmieren", {"days": 91}),
        T("z_axis", "Z-Linearstangen und Gewindespindeln reinigen und fetten", "Schmieren", {"days": 91}),
        T("lift_rail", "Hubschiene der linken Düse reinigen und ölen", "Schmieren", {"days": 30}, "Nur H2D/H2D Pro."),
        T("clean", "Druckraum, Heizbett, Kameras, Lüfter und Filterabdeckung reinigen", "Reinigen", {"days": 91},
          "Werkzeugkopf, Kameras, Flammensensor, Zusatzlüfter, Seitenwände, Abluft, Aktivkohle-Abdeckung."),
        CUTTER,
        T("hotend", "Hotend: Cold Pull", "Reinigen", {"kg": 5, "kg_abrasive": 2}, "Alle 5 Rollen, bei Carbonfaser alle 2 Rollen."),
        T("ext_gear", "Extruderzahnrad prüfen und reinigen", "Prüfen", {"days": 7}, WEEKLY, False),
    ],
}
CATALOG["H2S"] = [dict(t, key=t["key"]) for t in CATALOG["H2"] if t["key"] != "lift_rail"]
for t in CATALOG["H2S"]:
    if t["key"] == "x_axis":
        t["name"] = "X-Linearführung reinigen und ölen"
CATALOG["A1M"] = [t for t in CATALOG["A1"]]
CATALOG["OTHER"] = [
    T("rods", "Achsen reinigen und schmieren", "Schmieren", {"days": 30}),
    T("z_screw", "Gewindespindeln fetten", "Schmieren", {"days": 91}),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS maint_state (
  printer_id INTEGER, task_key TEXT, enabled INTEGER, days REAL, kg REAL, hours REAL,
  last_done TEXT, counted_from TEXT, PRIMARY KEY (printer_id, task_key)
);
CREATE TABLE IF NOT EXISTS maint_custom (
  id INTEGER PRIMARY KEY AUTOINCREMENT, printer_id INTEGER, name TEXT NOT NULL, days REAL, kg REAL, hours REAL, hint TEXT
);
CREATE TABLE IF NOT EXISTS maint_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, printer_id INTEGER, task_key TEXT, name TEXT, done_at TEXT, note TEXT
);
"""


def init_schema():
    with conn() as c:
        c.executescript(SCHEMA)


def family(model: str | None, serial: str | None) -> str:
    """Modellreihe aus Modellname bzw. Seriennummer."""
    m = (model or "").upper().replace("BAMBU LAB", "").strip()
    pre = (serial or "")[:3].upper()
    if "H2S" in m or pre == "093":
        return "H2S"
    if m.startswith("H2") or pre in ("094", "239"):
        return "H2"
    if "MINI" in m or m in ("A1M", "N1") or pre == "030":
        return "A1M"
    if m.startswith("A1") or pre == "039":
        return "A1"
    if m.startswith(("X1", "X2")) or pre in ("00M", "00W", "03W"):
        return "X1"
    if m.startswith(("P1", "P2")) or pre in ("01S", "01P", "22E"):
        return "P1"
    return "OTHER"


ABRASIVE = re.compile(r"(?:^|[\s\-+_/])(?:CF|GF)(?:$|[\s\-+_/])|CARBON|GLASS", re.I)


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")[:19]) if s else None
    except ValueError:
        return None


def _usage(c, pid: int) -> list[tuple]:
    """Druckhistorie eines Druckers → [(Ende, Stunden, Gramm, Gramm abrasiv)]"""
    mats = {r["id"]: f'{r["material"] or ""} {r["color_name"] or ""}' for r in c.execute("SELECT id, material, color_name FROM filaments")}
    out = []
    for r in c.execute("SELECT started, ended, usage FROM print_jobs WHERE printer_id=? AND ended IS NOT NULL", (pid,)):
        a, b = _dt(r["started"]), _dt(r["ended"])
        h = max(0.0, (b - a).total_seconds() / 3600) if a and b else 0.0
        g = ga = 0.0
        try:
            for u in json.loads(r["usage"] or "[]"):
                w = float(u.get("grams") or 0)
                g += w
                if ABRASIVE.search(mats.get(u.get("filament_ref"), "")):
                    ga += w
        except (ValueError, TypeError, AttributeError):
            pass
        if b:
            out.append((b, min(h, 240.0), g, ga))  # Ausreißer (nie beendete Jobs) begrenzen
    return out


def _tasks(c, p) -> list[dict]:
    fam = family(p["model"], p["serial"])
    base = [dict(t, custom=False) for t in CATALOG[fam]]
    for r in c.execute("SELECT * FROM maint_custom WHERE printer_id=? ORDER BY id", (p["id"],)):
        base.append({"key": f"c{r['id']}", "name": r["name"], "cat": "Eigene", "hint": r["hint"] or "", "on": True, "custom": True,
                     "iv": {k: r[k] for k in ("days", "kg", "hours") if r[k]}})
    return base


def _fmt_left(kind: str, left: float) -> str:
    if kind == "days":
        d = round(left)
        return "heute" if d == 0 else (f"in {d} Tagen" if d > 1 else "morgen") if d > 0 else f"seit {-d} {'Tag' if d == -1 else 'Tagen'}"
    if kind == "hours":
        return f"in {left:.0f} h Druck" if left >= 0 else f"{-left:.0f} h Druck überzogen"
    return (f"in {left:.1f} kg Filament" if left >= 0 else f"{-left:.1f} kg Filament überzogen").replace(".", ",")


def printer_status(c, p) -> dict:
    now = _now()
    fam = family(p["model"], p["serial"])
    usage = _usage(c, p["id"])
    st = {r["task_key"]: r for r in c.execute("SELECT * FROM maint_state WHERE printer_id=?", (p["id"],))}
    tasks = []
    for t in _tasks(c, p):
        s = st.get(t["key"])
        if s is None:  # erste Anzeige: ab jetzt zählen
            c.execute("INSERT OR IGNORE INTO maint_state (printer_id, task_key, counted_from) VALUES (?,?,?)",
                      (p["id"], t["key"], now.isoformat()))
            s = {"enabled": None, "days": None, "kg": None, "hours": None, "last_done": None, "counted_from": now.isoformat()}
        iv = dict(t["iv"])
        for k in ("days", "kg", "hours"):
            if s[k] is not None:
                iv[k] = s[k] or None  # 0 = Kriterium aus
        iv = {k: v for k, v in iv.items() if v}
        enabled = bool(t["on"] if s["enabled"] is None else s["enabled"])
        since_at = _dt(s["last_done"]) or _dt(s["counted_from"]) or now
        hrs = sum(u[1] for u in usage if u[0] > since_at)
        kg = sum(u[2] for u in usage if u[0] > since_at) / 1000
        kg_ab = sum(u[3] for u in usage if u[0] > since_at) / 1000
        days = (now - since_at).total_seconds() / 86400
        parts = []
        if iv.get("days"):
            parts.append(("days", days / iv["days"], iv["days"] - days))
        if iv.get("hours"):
            parts.append(("hours", hrs / iv["hours"], iv["hours"] - hrs))
        if iv.get("kg") or iv.get("kg_abrasive"):
            # abrasives Filament zählt im Verhältnis der beiden Intervalle stärker
            norm = iv.get("kg") or 0
            ab = iv.get("kg_abrasive") or 0
            if norm and ab:
                eff, lim = (kg - kg_ab) + kg_ab * norm / ab, norm
            elif norm:
                eff, lim = kg, norm
            else:
                eff, lim = kg_ab, ab
            parts.append(("kg", eff / lim, lim - eff))
        lead = max(parts, key=lambda x: x[1]) if parts else None
        prog = lead[1] if lead else 0
        status = "off" if not enabled else "due" if prog >= 1 else "soon" if prog >= 0.8 else "ok"
        tasks.append({
            "key": t["key"], "name": t["name"], "cat": t["cat"], "hint": t["hint"], "custom": t["custom"], "enabled": enabled,
            "interval": iv, "default_interval": t["iv"], "status": status, "progress": round(prog, 3),
            "due": _fmt_left(lead[0], lead[2]) if lead and enabled else "", "due_by": lead[0] if lead else None,
            "last_done": s["last_done"], "counted_from": None if s["last_done"] else s["counted_from"],
            "since": {"days": round(days, 1), "hours": round(hrs, 1), "kg": round(kg, 2), "kg_abrasive": round(kg_ab, 2)},
        })
    order = {"due": 0, "soon": 1, "ok": 2, "off": 3}
    tasks.sort(key=lambda x: (order[x["status"]], -x["progress"]))
    first = min((u[0] for u in usage), default=None)
    return {"id": p["id"], "name": p["name"] or p["serial"], "model": p["model"], "family": fam, "wiki": WIKI.get(fam),
            "totals": {"hours": round(sum(u[1] for u in usage), 1), "kg": round(sum(u[2] for u in usage) / 1000, 2),
                       "jobs": len(usage), "since": first.isoformat() if first else None},
            "due": sum(t["status"] == "due" for t in tasks), "soon": sum(t["status"] == "soon" for t in tasks), "tasks": tasks}


def _printer(c, pid):
    p = c.execute("SELECT * FROM printers WHERE id=?", (pid,)).fetchone()
    if not p:
        abort(404)
    return p


def _known_task(c, p, key) -> dict:
    t = next((t for t in _tasks(c, p) if t["key"] == key), None)
    if not t:
        abort(404)
    return t


@bp.get("")
def overview():
    with conn() as c:
        out = [printer_status(c, p) for p in c.execute("SELECT * FROM printers WHERE enabled=1 ORDER BY id").fetchall()]
    return jsonify({"printers": out, "due": sum(p["due"] for p in out), "soon": sum(p["soon"] for p in out)})


@bp.post("/<int:pid>/<key>/done")
def done(pid, key):
    b = request.get_json(silent=True) or {}
    when = _dt(b.get("date")) or _now()
    if when > _now() + timedelta(minutes=5):
        return jsonify({"error": "Datum liegt in der Zukunft"}), 400
    with conn() as c:
        p = _printer(c, pid)
        t = _known_task(c, p, key)
        c.execute("INSERT OR IGNORE INTO maint_state (printer_id, task_key, counted_from) VALUES (?,?,?)", (pid, key, _now().isoformat()))
        c.execute("UPDATE maint_state SET last_done=? WHERE printer_id=? AND task_key=? AND (last_done IS NULL OR last_done<?)",
                  (when.isoformat(), pid, key, when.isoformat()))
        c.execute("INSERT INTO maint_log (printer_id, task_key, name, done_at, note) VALUES (?,?,?,?,?)",
                  (pid, key, t["name"], when.isoformat(), (b.get("note") or "").strip()[:500] or None))
        return jsonify(printer_status(c, p))


@bp.put("/<int:pid>/<key>")
def update(pid, key):
    """Aufgabe ein-/ausschalten oder Intervall anpassen (Wert 0 = Kriterium aus, null = Standard)."""
    b = request.get_json(silent=True) or {}
    with conn() as c:
        p = _printer(c, pid)
        t = _known_task(c, p, key)
        c.execute("INSERT OR IGNORE INTO maint_state (printer_id, task_key, counted_from) VALUES (?,?,?)", (pid, key, _now().isoformat()))
        if "enabled" in b:
            c.execute("UPDATE maint_state SET enabled=? WHERE printer_id=? AND task_key=?", (1 if b["enabled"] else 0, pid, key))
        for k in ("days", "kg", "hours"):
            if k in b:
                v = b[k]
                v = None if v in (None, "") else max(0.0, float(v))
                if t["custom"]:
                    c.execute(f"UPDATE maint_custom SET {k}=? WHERE id=?", (v or None, int(key[1:])))
                else:
                    c.execute(f"UPDATE maint_state SET {k}=? WHERE printer_id=? AND task_key=?", (v, pid, key))
        if t["custom"] and b.get("name"):
            c.execute("UPDATE maint_custom SET name=? WHERE id=?", (b["name"].strip()[:120], int(key[1:])))
        return jsonify(printer_status(c, p))


@bp.post("/<int:pid>/custom")
def add_custom(pid):
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip()[:120]
    iv = {k: max(0.0, float(b[k])) for k in ("days", "kg", "hours") if b.get(k) not in (None, "")}
    if not name or not any(iv.values()):
        return jsonify({"error": "Name und mindestens ein Intervall (Tage, kg oder Stunden) angeben"}), 400
    with conn() as c:
        p = _printer(c, pid)
        c.execute("INSERT INTO maint_custom (printer_id, name, days, kg, hours, hint) VALUES (?,?,?,?,?,?)",
                  (pid, name, iv.get("days"), iv.get("kg"), iv.get("hours"), (b.get("hint") or "").strip()[:300] or None))
        return jsonify(printer_status(c, p))


@bp.delete("/<int:pid>/<key>")
def delete_custom(pid, key):
    with conn() as c:
        p = _printer(c, pid)
        t = _known_task(c, p, key)
        if not t["custom"]:
            return jsonify({"error": "Aufgaben aus dem Katalog lassen sich nur ausschalten"}), 400
        c.execute("DELETE FROM maint_custom WHERE id=?", (int(key[1:]),))
        c.execute("DELETE FROM maint_state WHERE printer_id=? AND task_key=?", (pid, key))
        return jsonify(printer_status(c, p))


@bp.get("/<int:pid>/log")
def log(pid):
    with conn() as c:
        _printer(c, pid)
        rows = c.execute("SELECT * FROM maint_log WHERE printer_id=? ORDER BY done_at DESC, id DESC LIMIT 200", (pid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.delete("/log/<int:lid>")
def log_delete(lid):
    """Versehentlich erledigt: Eintrag löschen, „zuletzt erledigt“ auf den vorigen Eintrag zurücksetzen."""
    with conn() as c:
        r = c.execute("SELECT * FROM maint_log WHERE id=?", (lid,)).fetchone()
        if not r:
            abort(404)
        c.execute("DELETE FROM maint_log WHERE id=?", (lid,))
        prev = c.execute("SELECT MAX(done_at) FROM maint_log WHERE printer_id=? AND task_key=?", (r["printer_id"], r["task_key"])).fetchone()[0]
        c.execute("UPDATE maint_state SET last_done=? WHERE printer_id=? AND task_key=?", (prev, r["printer_id"], r["task_key"]))
    return jsonify({"ok": True})
