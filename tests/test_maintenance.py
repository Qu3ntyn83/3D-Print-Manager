"""Wartung: Katalog je Modellreihe, Fälligkeit nach Tagen / Filament / Druckstunden, Erledigen, eigene Aufgaben."""
import json
from datetime import datetime, timedelta


def _printer(c, name, model, serial):
    return c.execute("INSERT INTO printers (name, serial, mode, model, enabled) VALUES (?,?,'lan',?,1)", (name, serial, model)).lastrowid


def _job(c, pid, end, hours, usage):
    s = end - timedelta(hours=hours)
    c.execute("INSERT INTO print_jobs (printer_id, job_key, name, started, ended, result, usage) VALUES (?,?,?,?,?,?,?)",
              (pid, f"m{pid}-{end.isoformat()}", "Test", s.isoformat(), end.isoformat(), "finish", json.dumps(usage)))


def test_family():
    from maintenance import family
    assert family("H2S", "0938X") == "H2S" and family("", "0938X") == "H2S"
    assert family("H2D", "") == "H2" and family("Bambu Lab X1 Carbon", "") == "X1" and family("P1S", "") == "P1"
    assert family("A1 mini", "") == "A1M" and family("A1", "") == "A1" and family("", "030X") == "A1M"
    assert family("Prusa MK4", "123") == "OTHER"


def test_maintenance_due_done_custom(client):
    from bambu import conn
    now = datetime.now().replace(microsecond=0)
    with conn() as c:
        pid = _printer(c, "Wartung-H2S", "H2S", "0938WARTUNG1")
        pla = c.execute("SELECT id FROM filaments WHERE material NOT LIKE '%CF%' AND material NOT LIKE '%GF%' LIMIT 1").fetchone()["id"]
        cf = c.execute("INSERT INTO filaments (brand, material, color_name, qty, colors) VALUES ('T','PA6-CF','Schwarz',1,'[]')").lastrowid
    me = lambda: next(p for p in client.get("/api/maintenance").json["printers"] if p["id"] == pid)  # noqa: E731
    p = me()
    keys = {t["key"] for t in p["tasks"]}
    assert p["family"] == "H2S" and "x_axis" in keys and "lift_rail" not in keys and "wiki.bambulab.com" in p["wiki"]
    assert all(t["status"] in ("ok", "off") for t in p["tasks"])                 # Start: zählt ab jetzt, nichts überfällig
    assert next(t for t in p["tasks"] if t["key"] == "ext_gear")["status"] == "off"  # wöchentlich: standardmäßig aus
    # Zählbeginn 40 Tage zurück + 2,5 kg PLA und 0,5 kg PA-CF gedruckt
    with conn() as c:
        c.execute("UPDATE maint_state SET counted_from=? WHERE printer_id=?", ((now - timedelta(days=40)).isoformat(), pid))
        _job(c, pid, now - timedelta(days=10), 30, [{"grams": 2500, "filament_ref": pla}])
        _job(c, pid, now - timedelta(days=5), 6, [{"grams": 500, "filament_ref": cf}])
    p = me()
    t = {x["key"]: x for x in p["tasks"]}
    assert t["x_axis"]["status"] == "due" and "seit 10 Tagen" == t["x_axis"]["due"]              # 30-Tage-Intervall
    assert t["y_rods"]["status"] == "ok"                                                         # 91 Tage
    assert t["cutter"]["since"]["kg"] == 3.0 and t["cutter"]["since"]["kg_abrasive"] == 0.5
    # Schneidmesser: 2,5 kg normal + 0,5 kg CF × 4/1,5 = 3,83 von 4 kg → bald fällig
    assert t["cutter"]["status"] == "soon" and 0.95 < t["cutter"]["progress"] < 0.97 and t["cutter"]["due_by"] == "kg"
    assert p["totals"]["jobs"] == 2 and p["totals"]["hours"] == 36 and p["totals"]["kg"] == 3.0
    assert client.get("/api/maintenance").json["due"] >= 1
    # erledigt → wieder ok, Protokoll; Erledigen in der Zukunft abgelehnt
    assert client.post(f"/api/maintenance/{pid}/x_axis/done", json={"date": (now + timedelta(days=2)).isoformat()}).status_code == 400
    r = client.post(f"/api/maintenance/{pid}/x_axis/done", json={"note": "Öl neu"}).json
    assert next(x for x in r["tasks"] if x["key"] == "x_axis")["status"] == "ok"
    log = client.get(f"/api/maintenance/{pid}/log").json
    assert log[0]["task_key"] == "x_axis" and log[0]["note"] == "Öl neu"
    # rückgängig: Protokolleintrag löschen → wieder fällig
    client.delete(f"/api/maintenance/log/{log[0]['id']}")
    assert next(x for x in me()["tasks"] if x["key"] == "x_axis")["status"] == "due"
    # nachträglich erledigt vor 3 Wochen → noch 9 Tage
    client.post(f"/api/maintenance/{pid}/x_axis/done", json={"date": (now - timedelta(days=21)).isoformat()})
    assert next(x for x in me()["tasks"] if x["key"] == "x_axis")["due"] == "in 9 Tagen"
    # Intervall anpassen und ausschalten
    r = client.put(f"/api/maintenance/{pid}/y_rods", json={"days": 30}).json
    assert next(x for x in r["tasks"] if x["key"] == "y_rods")["status"] == "due"
    r = client.put(f"/api/maintenance/{pid}/y_rods", json={"enabled": False}).json
    assert next(x for x in r["tasks"] if x["key"] == "y_rods")["status"] == "off"
    r = client.put(f"/api/maintenance/{pid}/y_rods", json={"days": None, "enabled": True}).json
    assert next(x for x in r["tasks"] if x["key"] == "y_rods")["interval"] == {"days": 91}
    # eigene Aufgabe nach Druckstunden
    assert client.post(f"/api/maintenance/{pid}/custom", json={"name": "Nur Name"}).status_code == 400
    r = client.post(f"/api/maintenance/{pid}/custom", json={"name": "Düse tauschen", "hours": 20}).json
    ck = next(x for x in r["tasks"] if x["custom"])
    assert ck["name"] == "Düse tauschen" and ck["since"]["hours"] == 0          # neue Aufgabe zählt ab jetzt
    assert client.delete(f"/api/maintenance/{pid}/x_axis").status_code == 400  # Katalog nur ausschaltbar
    r = client.delete(f"/api/maintenance/{pid}/{ck['key']}").json
    assert not any(x["custom"] for x in r["tasks"])
    assert client.post("/api/maintenance/999999/x_axis/done").status_code == 404
