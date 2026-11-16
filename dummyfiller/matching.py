"""Matchning av projektets tabeller och kolumner mot en annan databas (t.ex. produktion) där namnen kan skilja sig.

Projektets koppling sparas i Project.prod_mapping:
    {"tables":  {projektnyckel: {"schema": s, "name": n, "kind": "exakt"|"automatisk"|"manuell", "score": 0.93}},
     "columns": {projektnyckel: {projektkolumn: {"name": produktionskolumn, "kind": ..., "score": ...}}}}
"""
from __future__ import annotations

import difflib

from .inference import norm
from .model import Column, Project, Table

EXACT, AUTO, MANUAL = "exakt", "automatisk", "manuell"
TABLE_THRESHOLD, COLUMN_THRESHOLD = 0.6, 0.72

# vanliga engelska och förkortade namn -> svenska (jämförs efter normalisering)
SYNONYMS = {
    "pnr": "personnummer", "persnr": "personnummer", "personnr": "personnummer", "ssn": "personnummer", "socialsecuritynumber": "personnummer",
    "firstname": "fornamn", "givenname": "fornamn", "lastname": "efternamn", "surname": "efternamn", "familyname": "efternamn",
    "gender": "kon", "sex": "kon", "birthdate": "fodelsedatum", "dateofbirth": "fodelsedatum", "dob": "fodelsedatum",
    "email": "epost", "mail": "epost", "phone": "telefon", "tel": "telefon", "mobile": "mobil", "address": "adress",
    "street": "gatuadress", "zip": "postnummer", "zipcode": "postnummer", "postalcode": "postnummer", "postnr": "postnummer",
    "city": "ort", "town": "ort", "country": "land", "county": "lan", "municipality": "kommun",
    "amount": "belopp", "sum": "summa", "date": "datum", "dt": "datum", "time": "tid", "name": "namn", "description": "beskrivning",
    "desc": "beskrivning", "code": "kod", "number": "nummer", "nr": "nummer", "no": "nummer", "num": "nummer", "id": "id", "key": "id",
    "account": "konto", "costcenter": "ansvar", "kst": "ansvar", "invoice": "faktura", "supplier": "leverantor", "vendor": "leverantor",
    "patient": "patient", "visit": "besok", "encounter": "vardkontakt", "diagnosis": "diagnos", "diag": "diagnos", "procedure": "atgard",
    "created": "skapad", "createdat": "skapad", "updated": "andrad", "modified": "andrad", "employee": "anstalld", "staff": "personal",
    "unit": "enhet", "department": "avdelning", "quantity": "antal", "qty": "antal", "price": "pris", "status": "status",
    "start": "start", "end": "slut", "from": "fran", "to": "till", "valid": "giltig", "type": "typ", "category": "kategori",
    "clinic": "klinik", "hospital": "sjukhus", "careunit": "vardenhet", "admission": "inskrivning", "discharge": "utskrivning",
    "budget": "budget", "period": "period", "year": "ar", "month": "manad", "salary": "lon", "absence": "franvaro",
    "dental": "tand", "tooth": "tand", "treatment": "behandling",
}
_PREFIXES = ("tbl", "tb", "t", "dim", "d", "fact", "fakta", "f", "stg", "ref", "dw", "vw", "v", "src", "raw")


def _tokens(name: str) -> list[str]:
    return [t for t in norm(name).split("_") if t]


_LONG_PREFIXES = ("tbl", "dim", "fact", "fakta", "stg", "ref", "vw")


def canon(name: str, table: bool = False) -> str:
    """Jämförbar form: gemener, utan å/ä/ö och understreck, synonymer översatta, tabellprefix borttagna."""
    toks = _tokens(name)
    if table and len(toks) > 1 and toks[0] in _PREFIXES:
        toks = toks[1:]
    elif table and len(toks) == 1:  # tblpatient, dimkund
        for p in _LONG_PREFIXES:
            if toks[0].startswith(p) and len(toks[0]) > len(p) + 2:
                toks = [toks[0][len(p):]]
                break
    joined = "".join(toks)
    if joined in SYNONYMS:
        return SYNONYMS[joined]
    return "".join(SYNONYMS.get(t, t) for t in toks)


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def column_score(a: Column, b_name: str, b_kind: str) -> tuple[float, str]:
    if a.name == b_name:
        s, kind = 1.0, EXACT
    elif a.name.lower() == b_name.lower():
        s, kind = 0.98, EXACT
    else:
        ca, cb = canon(a.name), canon(b_name)
        s = 0.94 if ca == cb else 0.9 * _sim(ca, cb)
        if ca and cb and s < 0.94 and (ca.endswith(cb) or cb.endswith(ca)) and min(len(ca), len(cb)) >= 4:
            s = max(s, 0.8)  # t.ex. PatientPersonnummer ~ Personnummer
        kind = AUTO
    if b_kind and a.kind != b_kind and not (a.kind in ("int", "decimal", "float") and b_kind in ("int", "decimal", "float")) \
            and not ({a.kind, b_kind} <= {"date", "datetime"}):
        s -= 0.15  # olika slags datatyp: kopplas bara om namnen är mycket lika
    return s, kind


def match_columns(table: Table, prod_cols: list[dict], keep: dict | None = None) -> dict:
    """Kolumnkopplingar för en tabell. Manuella kopplingar i `keep` behålls; resten matchas automatiskt (en-till-en)."""
    keep = {k: v for k, v in (keep or {}).items() if v.get("kind") == MANUAL and any(p["name"] == v["name"] for p in prod_cols)}
    used = {v["name"] for v in keep.values()}
    pairs = []
    for c in table.columns:
        if c.computed or c.name in keep:
            continue
        for p in prod_cols:
            if p["name"] in used:
                continue
            s, kind = column_score(c, p["name"], p.get("kind", ""))
            if s >= COLUMN_THRESHOLD:
                pairs.append((s, c.name, p["name"], kind))
    out = dict(keep)
    for s, a, b, kind in sorted(pairs, key=lambda x: -x[0]):
        if a in out or b in used:
            continue
        out[a] = {"name": b, "kind": kind if s >= 0.94 else AUTO, "score": round(s, 2)}
        used.add(b)
    return out


def table_score(t: Table, p: dict) -> tuple[float, str]:
    if t.name == p["name"] and (t.schema or "") == (p["schema"] or ""):
        return 1.0, EXACT
    if t.name.lower() == p["name"].lower():
        return 0.97, EXACT
    ca, cb = canon(t.name, True), canon(p["name"], True)
    name = 0.95 if ca == cb else _sim(ca, cb)
    cols = [c for c in t.columns if not c.computed]
    if cols and p["columns"]:
        canon_prod = {canon(x["name"]) for x in p["columns"]}
        overlap = sum(canon(c.name) in canon_prod for c in cols) / len(cols)
    else:
        overlap = 0.0
    return 0.65 * name + 0.35 * overlap, AUTO


def prod_key(p: dict) -> str:
    return f"{p['schema']}.{p['name']}" if p.get("schema") else p["name"]


def auto_match(project: Project, prod_tables: list[dict], mapping: dict | None = None, reset: bool = False) -> dict:
    """Matchar projektets tabeller och kolumner. Manuella kopplingar behålls om inte `reset`."""
    mapping = {"tables": {}, "columns": {}} if reset or not mapping else {"tables": dict(mapping.get("tables") or {}),
                                                                          "columns": dict(mapping.get("columns") or {})}
    by_key = {prod_key(p): p for p in prod_tables}
    tables = {k: v for k, v in mapping["tables"].items() if v.get("kind") == MANUAL and prod_key(v) in by_key and project.table(k)}
    used = {prod_key(v) for v in tables.values()}
    pairs = []
    for t in project.tables:
        if t.key in tables:
            continue
        for p in prod_tables:
            if prod_key(p) in used:
                continue
            s, kind = table_score(t, p)
            if s >= TABLE_THRESHOLD:
                pairs.append((s, t.key, prod_key(p), kind))
    for s, a, b, kind in sorted(pairs, key=lambda x: -x[0]):
        if a in tables or b in used:
            continue
        p = by_key[b]
        tables[a] = {"schema": p["schema"], "name": p["name"], "kind": kind, "score": round(s, 2)}
        used.add(b)
    columns = {}
    for key, tm in tables.items():
        p = by_key[prod_key(tm)]
        columns[key] = match_columns(project.table(key), p["columns"], (mapping["columns"].get(key) if tm.get("kind") == MANUAL or not reset else None))
    return {"tables": tables, "columns": columns}


def link_table(project: Project, mapping: dict, prod_tables: list[dict], key: str, pkey: str | None) -> None:
    """Manuell tabellkoppling (pkey None tar bort). Kolumnerna matchas automatiskt för det nya paret."""
    tables, columns = mapping.setdefault("tables", {}), mapping.setdefault("columns", {})
    if pkey is None:
        tables.pop(key, None)
        columns.pop(key, None)
        return
    p = next(x for x in prod_tables if prod_key(x) == pkey)
    for other, tm in list(tables.items()):  # en produktionstabell kan bara höra till en projekttabell
        if other != key and prod_key(tm) == pkey:
            tables.pop(other)
            columns.pop(other, None)
    old = tables.get(key)
    tables[key] = {"schema": p["schema"], "name": p["name"], "kind": MANUAL, "score": 1.0}
    if old is None or prod_key(old) != pkey:
        columns[key] = match_columns(project.table(key), p["columns"])


def link_column(mapping: dict, key: str, col: str, prod_col: str | None) -> None:
    cols = mapping.setdefault("columns", {}).setdefault(key, {})
    if prod_col is None:
        cols.pop(col, None)
        return
    for other, v in list(cols.items()):
        if other != col and v["name"] == prod_col:
            cols.pop(other)
    cols[col] = {"name": prod_col, "kind": MANUAL, "score": 1.0}


def type_mismatch(col: Column, prod_kind: str) -> bool:
    groups = [{"int", "decimal", "float"}, {"date", "datetime"}]
    return bool(prod_kind) and col.kind != prod_kind and not any({col.kind, prod_kind} <= g for g in groups)


def summary(project: Project, mapping: dict, keys: list[str]) -> dict:
    tables = mapping.get("tables") or {}
    cols = mapping.get("columns") or {}
    n_tab = sum(1 for k in keys if k in tables)
    missing_cols = sum(1 for k in keys if k in tables for c in project.table(k).columns if not c.computed and c.name not in cols.get(k, {}))
    return {"tabeller": n_tab, "av": len(keys), "omatchade kolumner": missing_cols}
