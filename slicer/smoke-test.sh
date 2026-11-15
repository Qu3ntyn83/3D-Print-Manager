#!/usr/bin/env bash
# Prüft den laufenden Slicer-Dienst: erzeugt mit Bambu Studio selbst ein kleines Projekt (Würfel) und lässt es slicen.
#   bash slicer/smoke-test.sh [Containername] [URL]
set -euo pipefail
C="${1:-3d-manager-slicer}"; URL="${2:-http://127.0.0.1:8080}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp/cube.stl" <<'PY'
import struct, sys
v = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 10), (20, 0, 10), (20, 20, 10), (0, 20, 10)]
f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
with open(sys.argv[1], "wb") as o:
    o.write(b"\0" * 80 + struct.pack("<I", len(f)))
    for a, b, c in f:
        o.write(struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0))
PY
docker cp "$tmp/cube.stl" "$C:/tmp/cube.stl"
P=/opt/bambu/resources/profiles/BBL
docker exec "$C" sh -c "cd /tmp && /opt/bambu/AppRun --debug 1 --load-settings '$P/machine/Bambu Lab A1 0.4 nozzle.json;$P/process/0.20mm Standard @BBL A1.json' --load-filaments '$P/filament/Bambu PLA Basic @BBL A1.json' --export-3mf /tmp/proj.3mf /tmp/cube.stl >/dev/null 2>&1; test -s /tmp/proj.3mf"
docker cp "$C:/tmp/proj.3mf" "$tmp/proj.3mf"
curl -fsS "$URL/healthz"; echo
curl -sS -X POST --data-binary "@$tmp/proj.3mf" -H 'Content-Type: application/octet-stream' "$URL/slice" > "$tmp/out.json"
python3 - "$tmp/out.json" <<'PY'
import json, re, sys
d = json.load(open(sys.argv[1]))
assert d.get("ok"), d
secs = [int(x) for x in re.findall(r'key="prediction" value="(\d+)"', d["slice_info"])]
assert secs and secs[0] > 60, d["slice_info"][:400]
print(f"Slicer-Dienst ok: Bambu Studio {d['version']}, Würfel in {d['seconds']} s geslict, Druckzeit {secs[0]} s")
PY
echo "nicht zip" > "$tmp/x.3mf"
test "$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary "@$tmp/x.3mf" "$URL/slice")" = 400
