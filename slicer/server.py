"""Slicer-Dienst: nimmt eine 3MF entgegen, sliced sie mit Bambu Studio (CLI) und gibt slice_info.config zurück.

POST /slice   Body = 3MF-Datei  →  {"ok": true, "slice_info": "<config>…", "seconds": 8.8, "version": "02.09.01.70"}
GET  /healthz                   →  {"ok": true, "version": "…", "busy": false}

Nur im internen Docker-Netz betreiben (keine Anmeldung). Immer nur ein Auftrag gleichzeitig.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BAMBU = os.environ.get("BAMBU_BIN", "/opt/bambu/AppRun")
TIMEOUT = int(os.environ.get("SLICE_TIMEOUT", "1200"))
MAX_BYTES = int(os.environ.get("SLICE_MAX_MB", "600")) * 1024 * 1024
try:
    VERSION = open("/opt/bambu/VERSION").read().strip()
except OSError:
    VERSION = "?"
LOCK = threading.Lock()
PLATE = re.compile(r"<plate>.*?</plate>", re.S)


def run_cli(src: str, out: str, plate: int, timeout: float):
    """→ (slice_info-Text oder None, letzte Logzeilen)"""
    try:
        p = subprocess.run([BAMBU, "--slice", str(plate), "--debug", "1", "--export-3mf", out, src],
                           cwd=os.path.dirname(out), capture_output=True, text=True, errors="replace", timeout=timeout)
        log = (p.stdout + p.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return None, f"Zeitlimit von {int(timeout)} s überschritten"
    try:
        with zipfile.ZipFile(out) as z:
            txt = z.read("Metadata/slice_info.config").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None, log or f"Bambu Studio beendet mit Code {p.returncode}"
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    return (txt if 'key="prediction"' in txt else None), log


def slice_file(src: str, work: str) -> dict:
    t0 = time.time()
    txt, log = run_cli(src, os.path.join(work, "out.3mf"), 0, TIMEOUT)
    failed = []
    if txt is None:
        # Alle Platten auf einmal ging nicht (z. B. eine fehlerhafte Platte) → einzeln versuchen
        try:
            with zipfile.ZipFile(src) as z:
                n = len(PLATE.findall(z.read("Metadata/model_settings.config").decode("utf-8", "replace")))
        except (OSError, KeyError, zipfile.BadZipFile):
            n = 0
        blocks = []
        for i in range(1, n + 1) if n > 1 else []:
            left = TIMEOUT - (time.time() - t0)
            if left < 5:
                failed.append(i)
                continue
            one, _ = run_cli(src, os.path.join(work, f"out{i}.3mf"), i, left)
            got = [b for b in PLATE.findall(one or "") if f'key="index" value="{i}"' in b]
            (blocks.extend(got) if got else failed.append(i))
        if blocks:
            txt = "<config>\n" + "\n".join(blocks) + "\n</config>"
    if txt is None:
        tail = "\n".join(l for l in log.splitlines() if "[error]" in l or "rror" in l)[-800:] or log[-800:]
        return {"ok": False, "error": tail.strip() or "Slicen fehlgeschlagen", "seconds": round(time.time() - t0, 1), "version": VERSION}
    return {"ok": True, "slice_info": txt, "failed_plates": failed, "seconds": round(time.time() - t0, 1), "version": VERSION}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._json(200, {"ok": True, "version": VERSION, "busy": LOCK.locked()})
        self._json(404, {"ok": False, "error": "unbekannt"})

    def do_POST(self):
        if not self.path.startswith("/slice"):
            return self._json(404, {"ok": False, "error": "unbekannt"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"ok": False, "error": "Datei fehlt oder ist zu groß"})
        work = tempfile.mkdtemp(prefix="slice-")
        try:
            src = os.path.join(work, "in.3mf")
            with open(src, "wb") as f:
                left = n
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left or not zipfile.is_zipfile(src):
                return self._json(400, {"ok": False, "error": "keine gültige 3MF-Datei"})
            with LOCK:
                res = slice_file(src, work)
            self._json(200 if res["ok"] else 422, res)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def log_message(self, fmt, *args):
        if "/healthz" not in (args[0] if args else ""):
            print(self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"Slicer-Dienst bereit (Bambu Studio {VERSION})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), H).serve_forever()
