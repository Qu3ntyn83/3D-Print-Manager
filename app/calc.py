"""Kalkulation & Angebote (übernommen aus dem 3D Print Calculator).

GET  /api/calc/data       Konfiguration + Filamente aus dem Inventar + Drucker (Bambu-Konto und manuell)
PUT  /api/calc/config     Konfiguration speichern (Preisprofile, Druckerkosten, Absender, Logo, Angebotseinstellungen)
POST /api/calc/quote-no   nächste Angebotsnummer vergeben

Material- und Strompreise kommen aus dem Bestand bzw. den App-Einstellungen,
damit Kalkulation und Statistik mit denselben Zahlen rechnen.
"""
from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, abort, jsonify, request

from bambu import conn
from insights import price_per_g, setting

bp = Blueprint("calc", __name__, url_prefix="/api/calc")

SCHEMA = "CREATE TABLE IF NOT EXISTS calc_store (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
MAX_CONFIG = 4 * 1024 * 1024  # Logo als Data-URL passt hinein

CURRENCY_ISO = {"€": "EUR", "eur": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP", "chf": "CHF", "fr.": "CHF",
                "zł": "PLN", "pln": "PLN", "kč": "CZK", "czk": "CZK", "kr": "SEK", "sek": "SEK", "dkk": "DKK", "nok": "NOK",
                "ft": "HUF", "huf": "HUF", "¥": "JPY", "jpy": "JPY", "cny": "CNY", "cad": "CAD", "aud": "AUD"}

DEFAULT_CONFIG = {
    "version": 1,
    "settings": {"vat": 19, "klein": True, "round": "0.50", "valid": 14, "cur": None, "prefix": "ANG-", "next_no": 1},
    "sender": {"name": "", "company": "#Powerscripting", "street": "", "zip": "", "city": "", "mail": "", "phone": "",
               "web": "powerscripting.de", "taxid": "", "iban": "", "bank": ""},
    "logo": None,
    "profiles": [
        {"id": "fam", "name": "Freunde & Familie", "margin": 0, "rate": 0, "risk": 5},
        {"id": "priv", "name": "Verkauf privat", "margin": 40, "rate": 20, "risk": 10},
        {"id": "gew", "name": "Gewerblich", "margin": 30, "rate": 45, "risk": 12},
    ],
    "printer_costs": {},      # "b<id>" -> {price, life, watt, wear} für Drucker aus dem Bambu-Konto
    "manual_printers": [],    # [{key: "m…", name, price, life, watt, wear}] für weitere Drucker
    "defaults": {"printer": None, "profile": "priv", "prep": 10, "post": 3},
}


def init_schema():
    with conn() as c:
        c.execute(SCHEMA)


def _load(c) -> dict:
    row = c.execute("SELECT value FROM calc_store WHERE key='config'").fetchone()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if row:
        try:
            saved = json.loads(row["value"])
        except ValueError:
            saved = {}
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    if not cfg["settings"].get("cur"):
        sym = str(setting(c, "currency") or "€").strip().lower()
        cfg["settings"]["cur"] = CURRENCY_ISO.get(sym, "EUR")
    return cfg


def _save(c, cfg: dict):
    c.execute("INSERT INTO calc_store(key, value) VALUES('config', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(cfg, ensure_ascii=False),))


def _filaments(c) -> list[dict]:
    fils = {r["id"]: r for r in c.execute("SELECT * FROM filaments")}
    units: dict[int, list] = {}
    for u in c.execute("SELECT * FROM spool_units WHERE status != 'empty'"):
        units.setdefault(u["filament_id"], []).append(u)
    out = []
    for fid, f in fils.items():
        us = units.get(fid, [])
        # Preis je kg: Durchschnitt der vorhandenen Spulen, sonst Sortenpreis
        ppgs = [p for p in (price_per_g(u, f) for u in us) if p is not None]
        ppg = sum(ppgs) / len(ppgs) if ppgs else price_per_g(None, f)
        stock = sum((u["remaining_g"] if u["remaining_g"] is not None else (u["initial_g"] or 0)) or 0 for u in us)
        try:
            colors = json.loads(f["colors"] or "[]")
        except ValueError:
            colors = []
        name = " ".join(x for x in (f["material"], f["color_name"]) if x)
        out.append({"id": fid, "brand": f["brand"] or "", "material": f["material"] or "", "name": name or f"Filament {fid}",
                    "color": (colors[0] if colors else "#888888")[:7], "colors": colors,
                    "price_kg": round(ppg * 1000, 2) if ppg is not None else None, "stock_g": round(stock), "spools": len(us)})
    out.sort(key=lambda x: (-(x["stock_g"] > 0), x["material"].lower(), x["brand"].lower(), x["name"].lower()))
    return out


def _printers(c, cfg) -> list[dict]:
    watt = setting(c, "printer_power_w")
    out = []
    try:
        rows = c.execute("SELECT id, name, model, serial FROM printers ORDER BY id").fetchall()
    except Exception:  # noqa: BLE001 – Tabelle fehlt, solange das AMS-Modul nie lief
        rows = []
    for r in rows:
        key = f"b{r['id']}"
        cost = {"price": 0, "life": 5000, "watt": watt, "wear": 0.2, **(cfg["printer_costs"].get(key) or {})}
        out.append({"key": key, "name": r["name"] or r["model"] or f"Drucker {r['id']}", "model": r["model"], "source": "bambu", **cost})
    for p in cfg.get("manual_printers") or []:
        out.append({"source": "manual", "watt": watt, "life": 5000, "wear": 0.2, "price": 0, **p})
    if not out:  # ohne Drucker trotzdem mit Strom aus den Einstellungen rechnen
        cost = {"price": 0, "life": 5000, "watt": watt, "wear": 0, **(cfg["printer_costs"].get("default") or {})}
        out.append({"key": "default", "name": "Standarddrucker", "model": None, "source": "default", **cost})
    return out


@bp.get("/data")
def data():
    with conn() as c:
        cfg = _load(c)
        return jsonify({"config": cfg, "filaments": _filaments(c), "printers": _printers(c, cfg),
                        "kwh_price": setting(c, "kwh_price"), "printer_power_w": setting(c, "printer_power_w")})


@bp.put("/config")
def put_config():
    if (request.content_length or 0) > MAX_CONFIG:
        abort(413)
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Objekt erwartet"}), 400
    with conn() as c:
        cfg = _load(c)
        for k in DEFAULT_CONFIG:
            if k in body and k != "version":
                cfg[k] = body[k]
        _save(c, cfg)
        return jsonify({"ok": True, "config": cfg, "printers": _printers(c, cfg)})


@bp.post("/quote-no")
def quote_no():
    with conn() as c:
        cfg = _load(c)
        st = cfg["settings"]
        n = int(st.get("next_no") or 1)
        st["next_no"] = n + 1
        _save(c, cfg)
        return jsonify({"no": f"{st.get('prefix') or ''}{date.today().year}-{n:04d}", "next": n + 1})
