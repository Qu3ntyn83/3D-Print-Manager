"""3MF in die Kalkulation laden – Auswertung auf dem Server, mit allen Quellen für Druckzeit und Filament.

Reihenfolge je Platte (die erste Quelle mit Werten gewinnt):
  1. Datei selbst (slice_info.config bzw. G-Code-Kopf)                      → threemf.read()
  2. früheres Ergebnis des Slicer-Dienstes für genau diese Datei (SHA-1)     → Tabelle calc_slices
  3. MakerWorld-Druckprofil (Modell in der Bibliothek)                       → makerworld.profile_plates()
  4. nichts – Platte bleibt offen; auf Wunsch slict der Slicer-Dienst sie    → POST /api/calc/3mf/slice

Der Slicer-Dienst ist ein optionaler zweiter Container (Bambu Studio auf der Kommandozeile, siehe slicer/).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

import threemf
from bambu import DATA_DIR, conn

bp = Blueprint("calc3mf", __name__, url_prefix="/api/calc")

SLICER_URL = (os.environ.get("SLICER_URL") or "http://slicer:8080").rstrip("/")
SLICER_TIMEOUT = int(os.environ.get("SLICER_TIMEOUT", "1500"))
UPLOAD_DIR = DATA_DIR / "tmp" / "calc"
UPLOAD_KEEP_S = 12 * 3600

SCHEMA = """CREATE TABLE IF NOT EXISTS calc_slices (
  sha1 TEXT PRIMARY KEY, plates TEXT NOT NULL, failed TEXT, version TEXT, seconds REAL, created TEXT
)"""

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_health = {"at": 0.0, "val": None}


def init_schema():
    with conn() as c:
        c.execute(SCHEMA)


# ---------------------------------------------------------------- Slicer-Dienst
def slicer_status(fresh=False) -> dict:
    """Ist der Slicer-Dienst erreichbar? (30 s gemerkt, damit die Oberfläche nicht bei jedem Aufruf wartet)"""
    if not fresh and time.time() - _health["at"] < 30 and _health["val"] is not None:
        return _health["val"]
    val = {"available": False, "version": None, "busy": False}
    if os.environ.get("SLICER_URL", "x") != "":  # SLICER_URL="" schaltet den Dienst ausdrücklich ab
        try:
            with urllib.request.urlopen(f"{SLICER_URL}/healthz", timeout=1.5) as r:
                d = json.load(r)
            val = {"available": bool(d.get("ok")), "version": d.get("version"), "busy": bool(d.get("busy"))}
        except (OSError, ValueError):
            pass
    _health.update(at=time.time(), val=val)
    return val


def slicer_run(path: Path) -> dict:
    """Datei an den Slicer-Dienst schicken → {"ok", "plates", "failed", "version", "seconds"} bzw. {"ok": False, "error"}"""
    size = path.stat().st_size
    with open(path, "rb") as f:
        req = urllib.request.Request(f"{SLICER_URL}/slice", data=f, method="POST",
                                     headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=SLICER_TIMEOUT) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                d = json.load(e)
            except ValueError:
                d = {"ok": False, "error": f"Slicer-Dienst antwortet mit {e.code}"}
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Slicer-Dienst nicht erreichbar ({e})"}
    if not d.get("ok"):
        return {"ok": False, "error": d.get("error") or "Slicen fehlgeschlagen"}
    plates = threemf.parse_slice_info(d.get("slice_info") or "")
    if not plates:
        return {"ok": False, "error": "Slicer lieferte keine Druckzeiten"}
    return {"ok": True, "plates": plates, "failed": d.get("failed_plates") or [], "version": d.get("version"), "seconds": d.get("seconds")}


# ---------------------------------------------------------------- Auswertung
def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve(token: str):
    """Token → (Pfad, Dateiname, Bibliotheks-Datei-ID oder None)"""
    kind, _, ref = (token or "").partition(":")
    if kind == "u" and ref.isalnum():
        p = UPLOAD_DIR / f"{ref}.3mf"
        meta = UPLOAD_DIR / f"{ref}.name"
        if p.exists():
            return p, (meta.read_text(encoding="utf-8") if meta.exists() else "upload.3mf"), None
    if kind == "l" and ref.isdigit():
        import library
        with conn() as c:
            f = c.execute("SELECT id, name, kind FROM lib_files WHERE id=?", (int(ref),)).fetchone()
        if f and f["kind"] == "3mf" and library.file_path(f["id"], "3mf").exists():
            return library.file_path(f["id"], "3mf"), f["name"], f["id"]
    return None, None, None


def analyze(token: str, mw_live=True) -> dict | None:
    path, name, fid = _resolve(token)
    if not path:
        return None
    a = threemf.read(path)
    a.update(token=token, name=name, sha1=_sha1(path), notes=[])
    with conn() as c:
        cached = c.execute("SELECT * FROM calc_slices WHERE sha1=?", (a["sha1"],)).fetchone()
        model = None
        if fid:
            model = c.execute("SELECT m.* FROM lib_models m JOIN lib_files f ON f.model_id=m.id WHERE f.id=?", (fid,)).fetchone()
        elif a["mw"]:
            if a["mw"]["model_id"]:
                model = c.execute("SELECT * FROM lib_models WHERE mw_model_id=?", (a["mw"]["model_id"],)).fetchone()
            if not model and a["mw"]["profile_id"].isdigit():
                model = c.execute("SELECT * FROM lib_models WHERE mw_profile_id=?", (int(a["mw"]["profile_id"]),)).fetchone()
    if cached:
        threemf.merge(a["plates"], json.loads(cached["plates"]), threemf.SRC_SLICER)
        a["slicer_failed"] = json.loads(cached["failed"] or "[]")
    a["model"] = {"id": model["id"], "title": model["title"], "makerworld": bool(model["mw_design_id"])} if model else None
    if model and model["mw_design_id"] and any(not p["src"] for p in a["plates"]):
        import makerworld
        want = int(a["mw"]["profile_id"]) if a["mw"] and a["mw"]["profile_id"].isdigit() else None
        mw = makerworld.profile_plates(model["id"], profile_id=want, live=mw_live)
        if mw["plates"]:
            # Platten der Datei und des Profils müssen zusammenpassen – sonst lieber nichts übernehmen als Falsches
            if len(mw["plates"]) == len(a["plates"]) or {p["index"] for p in a["plates"]} <= {p["index"] for p in mw["plates"]}:
                if threemf.merge(a["plates"], mw["plates"], threemf.SRC_MW):
                    a["mw_profile"] = mw["profile"]
            else:
                a["notes"].append(f"MakerWorld-Druckprofil „{mw['profile'] or '?'}“ hat {len(mw['plates'])} Platten, die Datei {len(a['plates'])} – nicht übernommen.")
        elif mw["error"]:
            a["notes"].append(f"MakerWorld-Druckprofil nicht abrufbar: {mw['error']}")
    a["missing"] = [p["index"] for p in a["plates"] if not p["src"]]
    a["complete"] = bool(a["plates"]) and not a["missing"]
    a["slicer"] = slicer_status()
    return a


def _cleanup_uploads():
    if not UPLOAD_DIR.exists():
        return
    now = time.time()
    for p in UPLOAD_DIR.iterdir():
        try:
            if now - p.stat().st_mtime > UPLOAD_KEEP_S:
                p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- API
@bp.get("/slicer")
def slicer_info():
    return jsonify(slicer_status(fresh=request.args.get("fresh") == "1"))


@bp.post("/3mf")
def upload():
    """3MF hochladen und auswerten. Die Datei bleibt 12 h liegen, damit sie auf Wunsch geslict werden kann."""
    f = request.files.get("file")
    if not f or not (f.filename or "").lower().endswith(".3mf"):
        return jsonify({"error": "Bitte eine .3mf-Datei wählen"}), 400
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_uploads()
    ref = uuid.uuid4().hex
    path = UPLOAD_DIR / f"{ref}.3mf"
    f.save(path)
    (UPLOAD_DIR / f"{ref}.name").write_text(os.path.basename(f.filename)[:200], encoding="utf-8")
    try:
        a = analyze(f"u:{ref}")
    except Exception as e:  # noqa: BLE001 – kaputtes ZIP o. Ä.
        path.unlink(missing_ok=True)
        return jsonify({"error": f"Datei ist keine lesbare 3MF ({str(e)[:120]})"}), 400
    return jsonify(a)


@bp.get("/3mf/library/<int:fid>")
def from_library(fid):
    try:
        a = analyze(f"l:{fid}")
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Datei ist keine lesbare 3MF ({str(e)[:120]})"}), 400
    return jsonify(a) if a else (jsonify({"error": "Datei nicht gefunden"}), 404)


@bp.get("/3mf/model/<int:mid>")
def from_model(mid):
    """MakerWorld-Modell ohne heruntergeladene Datei: Platten allein aus dem Druckprofil."""
    import makerworld
    with conn() as c:
        m = c.execute("SELECT id, title, mw_design_id FROM lib_models WHERE id=?", (mid,)).fetchone()
    if not m or not m["mw_design_id"]:
        return jsonify({"error": "Kein MakerWorld-Modell"}), 404
    mw = makerworld.profile_plates(mid)
    plates = [{"index": int(p.get("index") or i), "name": p.get("name") or "", "objects": 0, "seconds": 0, "grams": 0, "filaments": [], "src": None}
              for i, p in enumerate(mw["plates"], 1)]
    threemf.merge(plates, mw["plates"], threemf.SRC_MW)
    if not plates:
        return jsonify({"error": mw["error"] or "MakerWorld nennt für dieses Modell keine Druckplatten"}), 502
    return jsonify({"kind": "bambu", "token": None, "name": m["title"], "title": m["title"], "printer": "", "plates": plates,
                    "missing": [p["index"] for p in plates if not p["src"]], "complete": all(p["src"] for p in plates),
                    "notes": [], "mw_profile": mw["profile"], "model": {"id": mid, "title": m["title"], "makerworld": True},
                    "slicer": slicer_status()})


def _slice_job(job: dict):
    token = job["token"]
    try:
        path, _, fid = _resolve(token)
        if not path:
            raise RuntimeError("Datei nicht mehr vorhanden – bitte erneut laden")
        job.update(state="running", started=time.time())
        res = slicer_run(path)
        if not res["ok"]:
            raise RuntimeError(res["error"])
        with conn() as c:
            c.execute("INSERT OR REPLACE INTO calc_slices (sha1, plates, failed, version, seconds, created) VALUES (?,?,?,?,?,datetime('now'))",
                      (_sha1(path), json.dumps(res["plates"]), json.dumps(res["failed"]), res["version"], res["seconds"]))
        a = analyze(token, mw_live=False)
        if fid:  # Bibliothek zeigt die Werte ab jetzt ebenfalls
            import library
            library.set_plates(fid, a["plates"])
        job.update(state="done", analysis=a)
    except Exception as e:  # noqa: BLE001
        job.update(state="error", error=str(e)[:600])
    job["ended"] = time.time()


@bp.post("/3mf/slice")
def slice_start():
    token = (request.get_json(silent=True) or {}).get("token") or ""
    if not _resolve(token)[0]:
        return jsonify({"error": "Datei nicht mehr vorhanden – bitte erneut laden"}), 404
    if not slicer_status(fresh=True)["available"]:
        return jsonify({"error": "Slicer-Dienst ist nicht erreichbar"}), 503
    with _jobs_lock:
        for jid, j in list(_jobs.items()):  # alte Aufträge vergessen; laufenden für dieselbe Datei wiederverwenden
            if j.get("ended") and time.time() - j["ended"] > 3600:
                del _jobs[jid]
            elif j["token"] == token and j["state"] in ("queued", "running"):
                return jsonify({"job": jid})
        jid = uuid.uuid4().hex[:12]
        job = _jobs[jid] = {"token": token, "state": "queued", "created": time.time()}
    threading.Thread(target=_slice_job, args=(job,), daemon=True).start()
    return jsonify({"job": jid})


@bp.get("/3mf/slice/<jid>")
def slice_state(jid):
    j = _jobs.get(jid)
    if not j:
        return jsonify({"state": "error", "error": "Auftrag unbekannt (Server neu gestartet?) – bitte erneut slicen"}), 404
    out = {"state": j["state"], "seconds": round(time.time() - j.get("started", j["created"]), 1)}
    if j["state"] == "done":
        out["analysis"] = j["analysis"]
    if j["state"] == "error":
        out["error"] = j["error"]
    return jsonify(out)
