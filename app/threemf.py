"""3MF-Projekte auswerten – eine Stelle für Kalkulation und Bibliothek.

Eine 3MF aus Bambu Studio / OrcaSlicer ist ein ZIP. Druckzeit und Filamentbedarf stehen darin NUR, wenn die
Platte vor dem Speichern geslict wurde:

  Metadata/model_settings.config   alle Platten des Projekts (Name, Objekte, Filament je Objekt) – immer da
  Metadata/project_settings.config Filamente des Projekts (Typ, Farbe), Drucker – immer da
  Metadata/slice_info.config       je GESLICTER Platte: prediction (s), weight (g), <filament used_g>
  Metadata/plate_N.gcode           nur in exportierten .gcode.3mf – Kopfzeilen mit Zeit und Gewicht
  3D/3dmodel.model                 Metadaten (Titel, MakerWorld: DesignModelId / DesignProfileId)

Normale Projektdateien („Speichern“) und fast alle MakerWorld-Downloads enthalten KEINE slice_info. Für solche
Platten gibt es drei weitere Quellen: das MakerWorld-Druckprofil, den Slicer-Dienst oder die Eingabe von Hand.

``read()`` liefert immer ALLE Platten des Projekts, jede mit ihrer Quelle (``src``) – ungeslicte nicht unterschlagen.
"""
from __future__ import annotations

import json
import re
import zipfile

SRC_FILE, SRC_GCODE, SRC_MW, SRC_SLICER = "slice_info", "gcode", "makerworld", "slicer"


def _attr(tag: str, name: str):
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _unescape(s: str) -> str:
    return (s or "").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def _meta(body: str) -> dict:
    return {_attr(t, "key"): _attr(t, "value") for t in re.findall(r"<metadata\b[^>]*>", body) if _attr(t, "key")}


DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.05, "ASA": 1.07, "TPU": 1.21, "PA": 1.14, "PC": 1.20, "PVA": 1.19, "HIPS": 1.04, "PET": 1.30}


def _grams_from_m(meters: float, typ: str | None) -> float:
    """Notbehelf, wenn der Slicer nur die Länge nennt (Profil ohne Dichte): 1,75-mm-Filament × Materialdichte."""
    if meters <= 0:
        return 0.0
    fam = re.split(r"[\s\-+_]", (typ or "PLA").upper())[0]
    return meters * 100 * 3.14159 * (0.175 / 2) ** 2 * DENSITY.get(fam, 1.24)


def parse_slice_info(text: str) -> list[dict]:
    """slice_info.config → geslicte Platten. Bewusst per Regex: ein unmaskiertes Zeichen in einem Objektnamen
    darf nicht die ganze Datei unlesbar machen."""
    out = []
    for i, m in enumerate(re.finditer(r"<plate>(.*?)</plate>", text, re.S), 1):
        body = m.group(1)
        kv = _meta(body)
        weight = _num(kv.get("weight"))
        tags = re.findall(r"<filament\b[^>]*>", body)
        fil = [{"id": _attr(t, "id") or str(k), "type": _attr(t, "type") or "", "color": (_attr(t, "color") or "#888888")[:7],
                "g": round(_num(_attr(t, "used_g")), 2)} for k, t in enumerate(tags, 1)]
        if not any(f["g"] > 0 for f in fil) and weight <= 0:  # Profil ohne Dichte: nur Längen bekannt
            for f, t in zip(fil, tags):
                f["g"] = round(_grams_from_m(_num(_attr(t, "used_m")), f["type"]), 2)
        used = [f for f in fil if f["g"] > 0]
        if not used and weight > 0:  # nur Gesamtgewicht bekannt → dem ersten Filament zuschreiben
            used = [{**(fil[0] if fil else {"id": "1", "type": "", "color": "#888888"}), "g": round(weight, 2)}]
        secs = int(_num(kv.get("prediction")))
        if secs <= 0 and not used:
            continue
        out.append({"index": int(_num(kv.get("index"), i)), "seconds": secs,
                    "grams": round(weight or sum(f["g"] for f in used), 2), "filaments": used})
    return out


def parse_gcode_head(head: str, index: int, proj: dict) -> dict | None:
    """Kommentarkopf einer Bambu/Orca-G-Code-Datei: Zeit, Gewicht je Filament, genutzte Filament-Nummern."""
    m = (re.search(r";\s*total estimated time\s*[:=]\s*([^;\n]+)", head, re.I)
         or re.search(r";\s*(?:model printing time|estimated printing time \(normal mode\))\s*[:=]\s*([^;\n]+)", head, re.I))
    secs = 0.0
    if m:
        for v, u in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", m.group(1)):
            secs += float(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u]
    g = (re.search(r";\s*total filament weight \[g\]\s*:\s*([^\n]+)", head, re.I)
         or re.search(r";\s*filament used \[g\]\s*=\s*([^\n]+)", head, re.I))
    grams = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", g.group(1))] if g else []
    ids = [int(x) for x in re.findall(r"\d+", (re.search(r";\s*filament\s*:\s*([\d,\s]+)\n", head, re.I) or [None, ""])[1])]
    types, cols = proj.get("filament_type") or [], proj.get("filament_colour") or []
    fil = []
    for k, w in enumerate(grams):
        fid = ids[k] if len(ids) == len(grams) else k + 1
        if w > 0:
            fil.append({"id": str(fid), "type": types[fid - 1] if 0 < fid <= len(types) else "",
                        "color": (cols[fid - 1] if 0 < fid <= len(cols) else "#888888")[:7], "g": round(w, 2)})
    if secs <= 0 and not fil:
        return None
    return {"index": index, "seconds": int(secs), "grams": round(sum(f["g"] for f in fil), 2), "filaments": fil}


def _project_plates(ms: str) -> list[dict]:
    """model_settings.config → alle Platten mit Namen, Objektanzahl und den Filament-Nummern ihrer Objekte."""
    extr: dict[str, set] = {}
    for m in re.finditer(r'<object\b[^>]*\bid="(\d+)"[^>]*>(.*?)</object>', ms, re.S):
        used = {int(v) for v in re.findall(r'<metadata\b[^>]*key="extruder"[^>]*value="(\d+)"', m.group(2)) if int(v) > 0}
        extr[m.group(1)] = used or {1}
    out = []
    for i, m in enumerate(re.finditer(r"<plate>(.*?)</plate>", ms, re.S), 1):
        body = m.group(1)
        kv = _meta(body.split("<model_instance>")[0])
        objs = re.findall(r'<model_instance>.*?key="object_id"\s+value="(\d+)".*?</model_instance>', body, re.S)
        fids = sorted(set().union(*(extr.get(o, {1}) for o in objs))) if objs else []
        out.append({"index": int(_num(kv.get("plater_id"), i)), "name": _unescape(kv.get("plater_name") or "").strip(),
                    "objects": len(objs), "filament_ids": fids})
    return out


def read(path) -> dict:
    """Wertet eine 3MF aus. ``path`` = Dateipfad oder geöffnete Datei.

    → {kind, app, title, printer, mw: {model_id, profile_id}|None, filaments: [...], plates: [...], sliced, complete}
    Platte: {index, name, objects, seconds, grams, filaments: [{id, type, color, g}], src}  – src None = keine Werte.
    """
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        def txt(n, limit=None):
            if n not in names:
                return ""
            with z.open(n) as f:
                return (f.read(limit) if limit else f.read()).decode("utf-8", "replace")

        main = next((n for n in names if n.lower() == "3d/3dmodel.model"), None)
        head = txt(main, 300_000) if main else ""
        md = {k: _unescape(v).strip() for k, v in re.findall(r'<metadata name="([^"]+)"[^>]*>([^<]*)<', head)}
        try:
            proj = json.loads(txt("Metadata/project_settings.config") or "{}")
        except ValueError:
            proj = {}
        ftypes, fcols = proj.get("filament_type") or [], proj.get("filament_colour") or []
        pfil = [{"id": str(i + 1), "type": t, "color": (fcols[i] if i < len(fcols) else "#888888")[:7]} for i, t in enumerate(ftypes)]

        ms = txt("Metadata/model_settings.config")
        base = _project_plates(ms) if ms else []
        sliced = {p["index"]: {**p, "src": SRC_FILE} for p in parse_slice_info(txt("Metadata/slice_info.config"))}
        for n in sorted(names):
            m = re.fullmatch(r"Metadata/plate_(\d+)\.gcode", n)
            if not m or (int(m.group(1)) in sliced and sliced[int(m.group(1))]["seconds"] > 0):
                continue
            with z.open(n) as f:
                g = parse_gcode_head(f.read(65536).decode("utf-8", "ignore"), int(m.group(1)), proj)
            if g:
                sliced[g["index"]] = {**g, "src": SRC_GCODE}

    if not base:  # kein Bambu-Projekt bzw. reine .gcode.3mf ohne Projektdaten
        base = [{"index": i, "name": "", "objects": 0, "filament_ids": []} for i in sorted(sliced)]
    plates = []
    for b in sorted(base, key=lambda p: p["index"]):
        s = sliced.get(b["index"])
        if s:
            plates.append({"index": b["index"], "name": b["name"], "objects": b["objects"], "seconds": s["seconds"],
                           "grams": s["grams"], "filaments": s["filaments"], "src": s["src"]})
        else:
            # ungeslict: welche Filamente die Platte nutzt, steht in den Objekten – Mengen gibt es noch nicht
            fil = [{**pfil[i - 1], "g": 0} for i in b["filament_ids"] if 0 < i <= len(pfil)] or ([{**pfil[0], "g": 0}] if pfil else [])
            plates.append({"index": b["index"], "name": b["name"], "objects": b["objects"], "seconds": 0, "grams": 0,
                           "filaments": fil, "src": None})
    bambu = bool(ms or sliced or "Metadata/project_settings.config" in names)
    mw = {"model_id": md.get("DesignModelId") or "", "profile_id": md.get("DesignProfileId") or ""}
    return {"kind": "bambu" if bambu else "other", "app": md.get("Application") or "", "title": md.get("Title") or "",
            "designer": md.get("Designer") or "", "printer": proj.get("printer_model") or "",
            "mw": mw if (mw["model_id"] or mw["profile_id"]) else None, "filaments": pfil, "plates": plates,
            "sliced": any(p["src"] for p in plates), "complete": bool(plates) and all(p["src"] for p in plates)}


def merge(plates: list[dict], extra: list[dict], src: str, only_missing=True) -> int:
    """Werte aus einer weiteren Quelle (MakerWorld-Profil, Slicer-Dienst) in die Plattenliste übernehmen.
    Zuordnung über den Plattenindex. → Anzahl ergänzter Platten."""
    by = {int(p.get("index") or i): p for i, p in enumerate(extra, 1)}
    n = 0
    for p in plates:
        e = by.get(p["index"])
        if not e or not (e.get("seconds") or 0) > 0 or (only_missing and p.get("src")):
            continue
        fil = [{"id": str(f.get("id") or k), "type": f.get("type") or "", "color": (f.get("color") or "#888888")[:7], "g": round(_num(f.get("g")), 2)}
               for k, f in enumerate(e.get("filaments") or [], 1) if _num(f.get("g")) > 0]
        grams = round(_num(e.get("grams")) or sum(f["g"] for f in fil), 2)
        if not fil and grams > 0:
            fil = [{**(p["filaments"][0] if p.get("filaments") else {"id": "1", "type": "", "color": "#888888"}), "g": grams}]
        p.update(seconds=int(e["seconds"]), grams=grams, filaments=fil, src=src)
        if e.get("name") and not p.get("name"):
            p["name"] = e["name"]
        n += 1
    return n
