"""3MF-Auswertung für die Kalkulation: Datei, Slicer-Dienst, MakerWorld-Druckprofil."""
import io
import json
import time
import zipfile

MODEL = ('<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
         '<metadata name="Application">BambuStudio-02.09.01.70</metadata><metadata name="Title">Kiste &amp; Deckel</metadata>{extra}'
         '<resources/><build/></model>')
PROJECT = json.dumps({"printer_model": "Bambu Lab H2S", "filament_type": ["PLA", "PETG", "PLA"],
                      "filament_colour": ["#FFFFFF", "#000000", "#FF0000"]})
# zwei Platten: Platte 1 „Kiste“ mit Objekt 2 (Filament 1 + Teil mit Filament 3), Platte 2 „Deckel“ mit Objekt 4 (Filament 2)
SETTINGS = """<?xml version="1.0" encoding="UTF-8"?><config>
<object id="2"><metadata key="name" value="Kiste <groß> & Co"/><metadata key="extruder" value="1"/>
  <part id="1" subtype="normal_part"><metadata key="extruder" value="3"/></part></object>
<object id="4"><metadata key="name" value="Deckel"/><metadata key="extruder" value="2"/></object>
<plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value="Kiste"/>
  <model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="0"/></model_instance></plate>
<plate><metadata key="plater_id" value="2"/><metadata key="plater_name" value="Deckel"/>
  <model_instance><metadata key="object_id" value="4"/><metadata key="instance_id" value="0"/></model_instance></plate>
</config>"""


def plate_xml(index, secs, weight, fils):
    f = "".join(f'<filament id="{i}" type="{t}" color="{c}" used_m="1.0" used_g="{g}"/>' for i, t, c, g in fils)
    # Objektname absichtlich mit unmaskierten Zeichen – daran scheiterte früher der XML-Parser
    return (f'<plate><metadata key="index" value="{index}"/><metadata key="prediction" value="{secs}"/>'
            f'<metadata key="weight" value="{weight}"/><object identify_id="1" name="A & B <x>" skipped="false"/>{f}</plate>')


def make_3mf(slice_plates=(), gcode=None, settings=SETTINGS, extra_meta="", project=PROJECT, salt=""):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", MODEL.format(extra=extra_meta) + salt)
        if project:
            z.writestr("Metadata/project_settings.config", project)
        if settings:
            z.writestr("Metadata/model_settings.config", settings)
        if slice_plates:
            z.writestr("Metadata/slice_info.config", "<config>" + "".join(slice_plates) + "</config>")
        for n, text in (gcode or {}).items():
            z.writestr(f"Metadata/plate_{n}.gcode", text)
    return buf.getvalue()


def test_read_all_plates_with_source():
    import threemf
    # komplett geslict
    a = threemf.read(io.BytesIO(make_3mf([plate_xml(1, 7200, "31.5", [(1, "PLA", "#FFFFFF", "30.0"), (3, "PLA", "#FF0000", "1.5"), (2, "PETG", "#000000", "0.00")]),
                                          plate_xml(2, 1800, "8.2", [(2, "PETG", "#000000", "8.2")])])))
    assert a["kind"] == "bambu" and a["complete"] and a["printer"] == "Bambu Lab H2S" and a["title"] == "Kiste & Deckel"
    p1, p2 = a["plates"]
    assert (p1["name"], p1["seconds"], p1["grams"], p1["src"]) == ("Kiste", 7200, 31.5, "slice_info")
    assert [(f["id"], f["g"]) for f in p1["filaments"]] == [("1", 30.0), ("3", 1.5)]        # ungenutztes Filament fällt weg
    assert p2["filaments"] == [{"id": "2", "type": "PETG", "color": "#000000", "g": 8.2}]
    # nur Platte 1 geslict → Platte 2 bleibt sichtbar, ohne Werte, mit dem Filament ihrer Objekte
    a = threemf.read(io.BytesIO(make_3mf([plate_xml(1, 7200, "31.5", [(1, "PLA", "#FFFFFF", "31.5")])])))
    assert not a["complete"] and a["sliced"]
    assert [(p["index"], p["src"], p["seconds"]) for p in a["plates"]] == [(1, "slice_info", 7200), (2, None, 0)]
    assert a["plates"][1]["filaments"] == [{"id": "2", "type": "PETG", "color": "#000000", "g": 0}]
    # Projekt ohne Slice-Daten: beide Platten, Filamente aus Objekt und Teil
    a = threemf.read(io.BytesIO(make_3mf()))
    assert not a["sliced"] and [p["src"] for p in a["plates"]] == [None, None]
    assert [f["id"] for f in a["plates"][0]["filaments"]] == ["1", "3"]
    # nur Gesamtgewicht / nur Länge
    a = threemf.read(io.BytesIO(make_3mf(['<plate><metadata key="index" value="1"/><metadata key="prediction" value="600"/><metadata key="weight" value="12.3"/></plate>',
                                          '<plate><metadata key="index" value="2"/><metadata key="prediction" value="977"/><metadata key="weight" value=""/>'
                                          '<filament id="1" type="PLA" color="#00AE42" used_m="0.71" used_g="0.00"/></plate>'])))
    assert a["plates"][0]["filaments"][0]["g"] == 12.3 and 2.0 < a["plates"][1]["filaments"][0]["g"] < 2.3
    # G-Code-Kopf statt slice_info (exportierte .gcode.3mf ohne Projektdaten)
    head = "; HEADER_BLOCK_START\n; model printing time: 1h 2m 3s; total estimated time: 1h 10m 0s\n; total filament weight [g] : 23.43,8.70\n; filament: 1,3\n; HEADER_BLOCK_END\n"
    a = threemf.read(io.BytesIO(make_3mf(gcode={1: head}, settings=None)))
    assert [(p["index"], p["seconds"], p["src"]) for p in a["plates"]] == [(1, 4200, "gcode")]
    assert [(f["id"], f["type"], f["g"]) for f in a["plates"][0]["filaments"]] == [("1", "PLA", 23.43), ("3", "PLA", 8.7)]
    # MakerWorld-Kennung, fremde 3MF
    a = threemf.read(io.BytesIO(make_3mf(extra_meta='<metadata name="DesignModelId">US123</metadata><metadata name="DesignProfileId">77</metadata>')))
    assert a["mw"] == {"model_id": "US123", "profile_id": "77"}
    assert threemf.read(io.BytesIO(make_3mf(settings=None, project=None)))["kind"] == "other"


def _wait(client, job):
    for _ in range(100):
        st = client.get(f"/api/calc/3mf/slice/{job}").json
        if st["state"] in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("Slice-Auftrag wird nicht fertig")


def test_calc_upload_and_slicer(client, monkeypatch):
    """Teilweise geslicte Datei hochladen → fehlende Platte vom Slicer-Dienst → Ergebnis bleibt für die Datei gemerkt."""
    import calc3mf
    data = make_3mf([plate_xml(1, 7200, "31.5", [(1, "PLA", "#FFFFFF", "31.5")])], salt="<!-- upload -->")
    up = lambda: client.post("/api/calc/3mf", data={"file": (io.BytesIO(data), "Kiste.3mf")}, content_type="multipart/form-data")  # noqa: E731
    monkeypatch.setattr(calc3mf, "slicer_status", lambda fresh=False: {"available": False, "version": None, "busy": False})
    a = up().json
    assert a["missing"] == [2] and not a["complete"] and a["slicer"]["available"] is False and a["token"].startswith("u:")
    assert client.post("/api/calc/3mf/slice", json={"token": a["token"]}).status_code == 503          # Dienst nicht da
    assert client.post("/api/calc/3mf/slice", json={"token": "u:gibtsnicht"}).status_code == 404
    assert client.post("/api/calc/3mf", data={"file": (io.BytesIO(b"kein zip"), "x.3mf")}, content_type="multipart/form-data").status_code == 400
    # Dienst da, Slicen schlägt fehl → Fehlertext kommt an
    monkeypatch.setattr(calc3mf, "slicer_status", lambda fresh=False: {"available": True, "version": "t", "busy": False})
    monkeypatch.setattr(calc3mf, "slicer_run", lambda path: {"ok": False, "error": "Objekt außerhalb der Platte"})
    st = _wait(client, client.post("/api/calc/3mf/slice", json={"token": a["token"]}).json["job"])
    assert st["state"] == "error" and "außerhalb" in st["error"]
    # Slicen klappt: liefert beide Platten – die in der Datei geslicte Platte 1 behält ihre eigenen Werte
    res = {"ok": True, "version": "t", "seconds": 1.0, "failed": [],
           "plates": [{"index": 1, "seconds": 1, "grams": 1, "filaments": [{"id": "1", "type": "PLA", "color": "#FFFFFF", "g": 1}]},
                      {"index": 2, "seconds": 1500, "grams": 9.5, "filaments": [{"id": "2", "type": "PETG", "color": "#000000", "g": 9.5}]}]}
    monkeypatch.setattr(calc3mf, "slicer_run", lambda path: res)
    st = _wait(client, client.post("/api/calc/3mf/slice", json={"token": a["token"]}).json["job"])
    assert st["state"] == "done" and st["analysis"]["complete"]
    assert [(p["index"], p["seconds"], p["src"]) for p in st["analysis"]["plates"]] == [(1, 7200, "slice_info"), (2, 1500, "slicer")]
    # dieselbe Datei später erneut laden → Werte sind sofort da, ohne neu zu slicen
    monkeypatch.setattr(calc3mf, "slicer_run", lambda path: (_ for _ in ()).throw(AssertionError("darf nicht erneut slicen")))
    again = up().json
    assert again["complete"] and again["plates"][1]["src"] == "slicer" and again["plates"][1]["grams"] == 9.5


def test_calc_library_makerworld_profile(client, monkeypatch):
    """MakerWorld-Datei ohne Slice-Daten in der Bibliothek: Werte aus dem Druckprofil – nur wenn die Platten passen."""
    import calc3mf
    import makerworld
    from ams import conn as dbconn
    monkeypatch.setattr(calc3mf, "slicer_status", lambda fresh=False: {"available": False, "version": None, "busy": False})
    data = make_3mf(extra_meta='<metadata name="DesignModelId">US990077</metadata><metadata name="DesignProfileId">4711</metadata>', salt="<!-- mw -->")
    mid = client.post("/api/library/models", data={"files": [(io.BytesIO(data), "Zug.3mf")]}, content_type="multipart/form-data").json["ids"][0]
    fid = client.get(f"/api/library/models/{mid}").json["file_list"][0]["id"]
    with dbconn() as c:
        c.execute("UPDATE lib_models SET source='makerworld', mw_design_id=990077001, mw_model_id='US990077' WHERE id=?", (mid,))
    seen = {}
    prof = {"plates": [{"index": 1, "name": "Lok", "seconds": 5400, "grams": 40, "filaments": [{"id": "1", "type": "PLA", "color": "#368CF9", "g": 40}]},
                       {"index": 2, "seconds": 3600, "grams": 25, "filaments": []}], "profile": "0.2 mm, 3 Wände", "error": None}
    monkeypatch.setattr(makerworld, "profile_plates", lambda m, profile_id=None, live=True: seen.update(mid=m, pid=profile_id) or prof)
    a = client.get(f"/api/calc/3mf/library/{fid}").json
    assert seen == {"mid": mid, "pid": 4711}                                   # Profil, aus dem die Datei stammt
    assert a["complete"] and a["mw_profile"] == "0.2 mm, 3 Wände" and a["model"]["id"] == mid
    assert [(p["seconds"], p["grams"], p["src"]) for p in a["plates"]] == [(5400, 40, "makerworld"), (3600, 25, "makerworld")]
    assert a["plates"][1]["filaments"][0]["g"] == 25                           # nur Gesamtgewicht → Filament der Platte
    # dieselbe Datei direkt hochgeladen: Modell wird über die Kennung in der Datei gefunden
    b = client.post("/api/calc/3mf", data={"file": (io.BytesIO(data), "Zug.3mf")}, content_type="multipart/form-data").json
    assert b["complete"] and b["model"]["id"] == mid
    # Profil mit anderer Plattenzahl → nichts übernehmen, Hinweis
    prof3 = {**prof, "plates": [{"index": 3, "seconds": 60, "grams": 1, "filaments": []}]}
    monkeypatch.setattr(makerworld, "profile_plates", lambda m, profile_id=None, live=True: prof3)
    c2 = client.get(f"/api/calc/3mf/library/{fid}").json
    assert c2["missing"] == [1, 2] and "nicht übernommen" in c2["notes"][0]
    assert client.get("/api/calc/3mf/library/99999999").status_code == 404


def test_calc_makerworld_model_without_file(client, monkeypatch):
    """MakerWorld-Modell, dessen Datei (noch) nicht geladen ist: Platten allein aus dem Druckprofil."""
    import makerworld
    from ams import conn as dbconn
    with dbconn() as c:
        mid = c.execute("INSERT INTO lib_models (title, source, mw_design_id, created_at, updated_at) VALUES ('Halter','makerworld',990077002,'x','x')").lastrowid
        own = c.execute("INSERT INTO lib_models (title, source, created_at, updated_at) VALUES ('Eigenes','upload','x','x')").lastrowid
    monkeypatch.setattr(makerworld, "profile_plates", lambda m, profile_id=None, live=True: {"profile": "Standard", "error": None, "plates": [
        {"index": 1, "name": "Klein", "seconds": 5910, "grams": 38, "filaments": [{"id": "1", "type": "PLA", "color": "#368CF9", "g": 38}]},
        {"index": 2, "name": "Groß", "seconds": 7738, "grams": 48, "filaments": [{"id": "1", "type": "PLA", "color": "#368CF9", "g": 48}]}]})
    a = client.get(f"/api/calc/3mf/model/{mid}").json
    assert a["complete"] and a["token"] is None and a["mw_profile"] == "Standard"
    assert [(p["name"], p["seconds"], p["src"]) for p in a["plates"]] == [("Klein", 5910, "makerworld"), ("Groß", 7738, "makerworld")]
    assert client.get(f"/api/calc/3mf/model/{own}").status_code == 404
