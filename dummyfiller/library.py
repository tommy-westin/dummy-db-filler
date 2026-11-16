"""Generatorbiblioteket: egna generatorer och ändringar i de inbyggda listorna.

Biblioteket är gemensamt för alla projekt och sparas i den lokala databasen (se store.py). Det kan exporteras till
en YAML-fil och delas i teamet.

Egna generatorer finns i två slag:
- Uppslagstabell: en tabell med värden som hör ihop radvis (t.ex. ansvar, benämning och förvaltning). Kolumner som
  använder samma tabell och grupp hämtar från samma rad, och i kodtabeller delas raderna ut i ordning.
- Förinställning: en befintlig generator med sparade inställningar (t.ex. ett mönster för fakturanummer). Ändras
  förinställningen ändras alla kolumner som använder den.

Projekt som använder en egen generator får en kopia av den (Project.custom_generators), så att projektet fungerar
även hos någon som saknar generatorn i sitt bibliotek. Finns den i biblioteket är det bibliotekets version som gäller.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from . import care, generators, region, rules, store, vocab
from .generators import GROUP, REGISTRY, GenSpec, Param, _weighted, defaults

PREFIX = "egen."
GROUP_LABEL = "Egna"
CONTEXT_TYPES = ("column", "fk", "parent_column", "list")  # ställs in per kolumn, inte i förinställningen

# ---------------------------------------------------------------- inbyggda listor som går att ändra


@dataclass
class ListSpec:
    key: str
    label: str
    group: str
    get: Callable[[], list]
    columns: list[tuple[str, str]]  # (rubrik, typ): text, opt (tom = saknas), int, float, list (separerad med ;)
    help: str = ""
    scalar: bool = False  # listan består av enskilda värden, inte rader


def _attr(module, name):
    return lambda: getattr(module, name)


_WEIGHT = ("Vikt", "float")
LIST_SPECS: list[ListSpec] = [
    ListSpec("region.accounts", "Kontoplan", "Ekonomi", _attr(region, "ACCOUNTS"),
             [("Konto", "text"), ("Benämning", "text"), ("Belopp min", "float"), ("Belopp max", "float"), _WEIGHT],
             "Kontonummer och benämning. Beloppsintervallet styr generatorn 'Belopp (rimligt för kontot)'. Konton som börjar på 3 räknas som intäkter."),
    ListSpec("region.cost_centers", "Ansvar / kostnadsställen", "Ekonomi", _attr(region, "COST_CENTERS"),
             [("Ansvar", "text"), ("Benämning", "text"), ("Förvaltning", "text"), _WEIGHT],
             "Används för ansvar, organisationsenheter och förvaltning."),
    ListSpec("region.activities", "Verksamheter", "Ekonomi", _attr(region, "ACTIVITIES"), [("Kod", "text"), ("Benämning", "text"), _WEIGHT]),
    ListSpec("region.titles", "Befattningar och löner", "Personal", _attr(region, "TITLES"),
             [("Befattning", "text"), ("Yrkeskategori", "text"), ("Lön min", "float"), ("Lön max", "float"), _WEIGHT],
             "Månadslönen hamnar inom intervallet för befattningen på samma rad."),
    ListSpec("region.dental_procedures", "Tandvårdsåtgärder", "Tandvård", _attr(region, "DENTAL_PROCEDURES"),
             [("Kod", "text"), ("Text", "text"), ("Pris min", "float"), ("Pris max", "float"), ("Antal ytor", "int"),
              ("Tandgrupp", "opt"), ("Diagnos", "text"), _WEIGHT],
             "Tandgrupp: fram, bak, valfri eller tomt (åtgärden gäller ingen enskild tand). Antal ytor används för fyllningar."),
    ListSpec("region.dental_diagnoses", "Tandvårdsdiagnoser", "Tandvård", _attr(region, "DENTAL_DIAGNOSES"), [("Kod", "text"), ("Text", "text")]),
    ListSpec("region.dental_clinics", "Folktandvårdskliniker", "Tandvård", _attr(region, "_FTV"), [("Klinik", "text")], scalar=True),
    ListSpec("care.diagnoses", "Diagnoser (ICD-10-SE)", "Vård", _attr(care, "DIAGNOSES"), [("Kod", "text"), ("Text", "text"), _WEIGHT],
             "Vanliga diagnoser. Hela kodverk läses hellre in under fliken Kodverk."),
    ListSpec("care.procedures", "Åtgärder (KVÅ)", "Vård", _attr(care, "PROCEDURES"), [("Kod", "text"), ("Text", "text"), _WEIGHT]),
    ListSpec("care.drugs", "Läkemedel (ATC)", "Vård", _attr(care, "DRUGS"),
             [("ATC-kod", "text"), ("Substans", "text"), ("Beredningsform", "text"), ("Styrkor", "list"), _WEIGHT],
             "Flera styrkor skiljs åt med semikolon, t.ex. 500 mg; 1 g."),
    ListSpec("care.labs", "Labbanalyser", "Vård", _attr(care, "LABS"),
             [("Analys", "text"), ("Enhet", "text"), ("Referens min", "float"), ("Referens max", "float"), ("Decimaler", "int"), _WEIGHT]),
    ListSpec("care.clinics", "Kliniker", "Vård", _attr(care, "CLINICS"), [("Klinik", "text")], scalar=True),
    ListSpec("care.notes", "Journalanteckningar", "Vård", _attr(care, "CARE_NOTES"), [("Anteckning", "text")], scalar=True),
    ListSpec("vocab.cities", "Orter", "Adress", _attr(vocab, "SWEDISH_CITIES"),
             [("Ort", "text"), ("Kommun", "text"), ("Län", "text"), ("Postnummerprefix", "list"), _WEIGHT],
             "Orter som personer, leverantörer och enheter får. Flera postnummerprefix skiljs åt med semikolon."),
    ListSpec("vocab.notes", "Administrativa anteckningar", "Text", _attr(vocab, "NOTES"), [("Anteckning", "text")], scalar=True),
]
_PRESET_LABELS = {
    "status": "Status", "case_status": "Ärendestatus", "payment": "Betalsätt", "priority": "Prioritet", "department": "Avdelningar (administration)",
    "role": "Användarroller", "language": "Språk", "currency_code": "Valutakoder", "currency": "Valutor", "country": "Länder",
    "country_code": "Landskoder", "vat_rate": "Momssatser", "category": "Kategorier", "invoice_status": "Fakturastatus",
    "payment_terms": "Betalvillkor", "budget_version": "Budgetversioner", "supplier_type": "Leverantörstyper", "hr_absence": "Frånvaroorsaker",
    "hr_pay_type": "Lönearter", "hr_employment_form": "Anställningsformer", "hr_administration": "Förvaltningar",
    "dental_patient_type": "Patienttyper (tandvård)", "care_ward": "Vårdavdelningar", "care_contact_type": "Kontakttyper",
    "care_form": "Vårdformer", "care_profession": "Yrkeskategorier (vård)", "care_visit_type": "Besökstyper", "care_triage": "Triagenivåer",
    "care_referral_status": "Remisstatus", "care_admission": "Inskrivningssätt", "care_discharge": "Utskrivningssätt",
    "care_booking_status": "Bokningsstatus", "care_fee": "Patientavgifter", "care_diagnosis_type": "Diagnostyper",
}
for _k in vocab.PRESETS:
    LIST_SPECS.append(ListSpec(f"preset.{_k}", _PRESET_LABELS.get(_k, _k), "Förvalda värdelistor", (lambda k=_k: vocab.PRESETS[k]),
                               [("Värde", "text"), _WEIGHT],
                               "Förvalda värdelistor används när kolumner tolkas automatiskt, t.ex. för en kolumn som heter Status. "
                               "Ändringen gäller kolumner som tolkas efter ändringen – för befintliga kolumner: 'Återställ till automatiskt förslag'."))
SPECS = {s.key: s for s in LIST_SPECS}
_ORIGINALS = {s.key: copy.deepcopy(s.get()) for s in LIST_SPECS}


def _cell(value, typ: str):
    if value is None or (isinstance(value, float) and value != value) or (isinstance(value, str) and not value.strip()):
        return None
    if typ == "int":
        return int(round(float(str(value).replace(",", ".").replace(" ", ""))))
    if typ == "float":
        f = float(str(value).replace(",", ".").replace(" ", ""))
        return int(f) if f.is_integer() else f
    if typ == "list":
        return [x.strip() for x in str(value).split(";") if x.strip()] if not isinstance(value, list) else value
    return str(value).strip()


def to_rows(spec: ListSpec, items: list) -> list[list]:
    """Listans poster som tabellrader (för visning och redigering)."""
    rows = []
    for item in items:
        if spec.key.startswith("preset."):
            val, _, w = str(item).rpartition("|") if "|" in str(item) else (str(item), "", "1")
            rows.append([val.strip(), _cell(w, "float")])
        elif spec.scalar:
            rows.append([item])
        else:
            rows.append(["; ".join(v) if typ == "list" and isinstance(v, list) else ("" if v is None else v)
                         for v, (_, typ) in zip(item, spec.columns)])
    return rows


def from_rows(spec: ListSpec, rows: list[list]) -> list:
    """Tabellrader tillbaka till listans format. Tomma rader hoppas över; felaktiga tal ger ValueError med radnummer."""
    out = []
    for n, row in enumerate(rows, start=1):
        row = list(row) + [None] * (len(spec.columns) - len(row))
        if _cell(row[0], "text") is None:
            continue
        try:
            cells = [_cell(v, typ) for v, (_, typ) in zip(row, spec.columns)]
        except ValueError:
            raise ValueError(f"Rad {n}: ogiltigt tal i '{spec.label}'.")
        for i, (name, typ) in enumerate(spec.columns):
            if cells[i] is None and typ in ("int", "float"):
                cells[i] = 1 if name == "Vikt" else 0
            if cells[i] is None and typ == "text":
                cells[i] = ""
            if cells[i] is None and typ == "list":
                cells[i] = []
        if spec.key.startswith("preset."):
            out.append(f"{cells[0]} | {cells[1]:g}")
        elif spec.scalar:
            out.append(cells[0])
        else:
            out.append(tuple(cells))
    if not out:
        raise ValueError(f"'{spec.label}' måste ha minst en rad.")
    return out


def _set_list(spec: ListSpec, items: list) -> None:
    if spec.key.startswith("preset."):
        vocab.PRESETS[spec.key.split(".", 1)[1]] = list(items)
    else:
        target = spec.get()
        target[:] = items  # samma listobjekt: alla generatorer ser ändringen


# ---------------------------------------------------------------- egna generatorer

def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "generator"


def new_key(name: str, taken: set[str]) -> str:
    base = PREFIX + slug(name)
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def table_fields(defn: dict) -> list[str]:
    return [c for c in defn.get("columns") or [] if c != defn.get("weight")]


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def make_spec(defn: dict, key: str | None = None, origin: str = "") -> GenSpec:
    key = key or defn["key"]
    name = defn.get("name") or key
    desc = (defn.get("description") or "").strip()
    note = f" ({origin})" if origin else ""
    if defn.get("kind") == "table":
        cols = list(defn.get("columns") or [])
        rows = [[_clean(v) for v in r] for r in defn.get("rows") or [] if any(_clean(v) is not None for v in r)]
        fields = table_fields(defn) or cols
        wi = cols.index(defn["weight"]) if defn.get("weight") in cols else None
        weights = []
        for r in rows:
            try:
                weights.append(max(0.0, float(str(r[wi]).replace(",", "."))) if wi is not None and r[wi] is not None else 1.0)
            except ValueError:
                weights.append(1.0)

        def func(ctx, p, _rows=rows, _cols=cols, _w=weights, _key=key):
            if not _rows:
                raise ValueError("uppslagstabellen är tom")

            def build():
                if ctx.table.category in ("reference", "location"):  # kodtabell: en rad per tabellrad, i ordning
                    return _rows[(ctx.index + ctx.offset) % len(_rows)]
                return _weighted(ctx.rng, _rows, _w) if sum(_w) > 0 else ctx.rng.choice(_rows)
            row = ctx.entity(f"{_key}:{p.get('group') or ''}", build)
            field = p.get("field") if p.get("field") in _cols else fields[0]
            return row[_cols.index(field)]

        params = [Param("field", "Fält", "select", fields[0] if fields else "", fields,
                        help="Vilken kolumn i uppslagstabellen som ska användas. Kolumner med samma grupp hämtar från samma rad."), GROUP]
        help = (desc + " " if desc else "") + f"Uppslagstabell med {len(rows)} rader och fälten {', '.join(fields)}.{note}"
        return GenSpec(key, name, GROUP_LABEL, func, params, help.strip())

    base = defn.get("base") or "constant"
    bspec = REGISTRY.get(base)
    if bspec is None or base.startswith(PREFIX):
        def missing(ctx, p, _b=base):
            raise ValueError(f"generatorn '{_b}' som förinställningen bygger på finns inte")
        return GenSpec(key, name, GROUP_LABEL, missing, [], f"Bygger på en generator som saknas: {base}.{note}")
    saved = {**defaults(base), **(defn.get("params") or {})}
    ctx_params = [p for p in bspec.params if p.type in CONTEXT_TYPES or p.name == "group"]
    ctx_names = {p.name for p in ctx_params}

    def func(ctx, p, _f=bspec.func, _saved=saved, _ctx=ctx_names):
        return _f(ctx, {**_saved, **{k: v for k, v in p.items() if k in _ctx}})

    help = (desc + " " if desc else "") + f"Förinställning av '{generators.label_of(base)}'.{note}"
    return GenSpec(key, name, GROUP_LABEL, func, list(ctx_params), help.strip())


def size_of(key: str) -> int | None:
    """Antal rader i en uppslagstabell (för radantalet i kodtabeller)."""
    defn = _active.get(key)
    if defn and defn.get("kind") == "table":
        return len([r for r in defn.get("rows") or [] if any(_clean(v) is not None for v in r)])
    return None


# ---------------------------------------------------------------- inläsning och tillämpning

_active: dict[str, dict] = {}  # nyckel -> definition, för det som är registrerat just nu
_origin: dict[str, str] = {}  # nyckel -> "" (biblioteket) eller "från projektet"
_overrides: set[str] = set()
_signature = None
_extra: dict = {}  # bibliotek som lagts på från fil utan att sparas (kommandoradens --bibliotek)
_codebooks: dict[str, list] = {}  # kodverk: diagnosis / procedure / drug -> [[kod, text], ...]
_test_pnr: list[str] = []  # officiella testpersonnummer
CODEBOOK_KINDS = ("diagnosis", "procedure", "drug")


def _load_all() -> dict[str, dict]:
    out = {"generator": {}, "list": {}, "codebook": {}, "testpnr": {}}
    for kind, key, content in store.lib_items():
        if kind in out:
            out[kind][key] = content
    return out


def _load_db() -> tuple[dict, dict]:
    a = _load_all()
    return a["generator"], a["list"]


def refresh(project=None, force: bool = False) -> None:
    """Registrerar bibliotekets generatorer och tillämpar ändrade listor. Billig när inget har ändrats."""
    global _signature
    snap = (project.custom_generators if project is not None else None) or {}
    sig = (str(store.db_path()), store.lib_revision(), tuple(sorted((k, id(v)) for k, v in snap.items())), id(_extra))
    if sig == _signature and not force:
        return
    _signature = sig
    everything = _load_all()
    gens, lists = everything["generator"], everything["list"]
    gens.update(_extra.get("generators") or {})
    lists.update(_extra.get("lists") or {})
    _codebooks.clear()
    _codebooks.update({k: v for k, v in everything["codebook"].items() if v})
    _codebooks.update(_extra.get("codebooks") or {})
    _test_pnr[:] = _extra.get("test_pnr") or everything["testpnr"].get("lista") or []
    # listor: återställ originalen och lägg på ändringarna
    for spec in LIST_SPECS:
        _set_list(spec, copy.deepcopy(_ORIGINALS[spec.key]))
    _overrides.clear()
    for key, items in lists.items():
        spec = SPECS.get(key)
        if spec is not None and items:
            _set_list(spec, from_rows(spec, items) if items and isinstance(items[0], list) else items)
            _overrides.add(key)
    region.rebuild()
    # generatorer: ta bort de gamla och registrera bibliotekets, och projektets kopior av sådana som saknas
    for k in [k for k in REGISTRY if k.startswith(PREFIX) and not k.startswith(PREFIX + "__")]:
        del REGISTRY[k]
    _active.clear()
    _origin.clear()
    for key, defn in list(gens.items()) + [(k, v) for k, v in snap.items() if k not in gens]:
        origin = "" if key in gens else "från projektet – saknas i ditt bibliotek"
        try:
            REGISTRY[key] = make_spec(defn, key, origin)
        except Exception:
            continue
        _active[key], _origin[key] = defn, origin
    generators.LIST_REVISION += 1
    generators._build_labels()


def is_overridden(list_key: str) -> bool:
    return list_key in _overrides


def custom_generators() -> dict[str, dict]:
    """Bibliotekets egna generatorer (inte projektkopior)."""
    return {k: v for k, v in _active.items() if not _origin.get(k)}


def origin(key: str) -> str:
    return _origin.get(key, "")


def save_generator(defn: dict) -> None:
    store.lib_put("generator", defn["key"], defn)
    refresh(force=True)


def delete_generator(key: str) -> None:
    store.lib_delete("generator", key)
    refresh(force=True)


def save_list(list_key: str, rows: list[list]) -> None:
    from_rows(SPECS[list_key], rows)  # kontrollera innan något sparas
    store.lib_put("list", list_key, [list(r) for r in rows])
    refresh(force=True)


def reset_list(list_key: str) -> None:
    store.lib_delete("list", list_key)
    refresh(force=True)


def codebook(kind: str) -> list | None:
    """Ett inläst kodverk i domänbiblioteket (t.ex. hela ICD-10-SE), eller None."""
    return _codebooks.get(kind)


def save_codebook(kind: str, pairs: list[list]) -> None:
    store.lib_put("codebook", kind, [list(p) for p in pairs])
    refresh(force=True)


def delete_codebook(kind: str) -> None:
    store.lib_delete("codebook", kind)
    refresh(force=True)


def test_pnr() -> list[str]:
    """Officiella testpersonnummer i domänbiblioteket (tom lista om inga är inlästa)."""
    return _test_pnr


def save_test_pnr(values: list[str]) -> None:
    store.lib_put("testpnr", "lista", [str(v).strip() for v in values if str(v).strip()])
    refresh(force=True)


def delete_test_pnr() -> None:
    store.lib_delete("testpnr", "lista")
    refresh(force=True)


def original_rows(list_key: str) -> list[list]:
    return to_rows(SPECS[list_key], _ORIGINALS[list_key])


def current_rows(list_key: str) -> list[list]:
    return to_rows(SPECS[list_key], SPECS[list_key].get())


def snapshot_into(project) -> None:
    """Lägger en kopia av de egna generatorer som projektet använder i projektet (för delning och kommandoraden)."""
    used = {c.generator for t in project.tables for c in t.columns if c.generator.startswith(PREFIX)}
    snap = {k: v for k, v in (project.custom_generators or {}).items() if k in used}
    for k in used:
        if k in _active and not _origin.get(k):
            snap[k] = _active[k]
    if snap != (project.custom_generators or {}):
        project.custom_generators = copy.deepcopy(snap)


def usage(project, key: str) -> list[str]:
    return [f"{t.name}.{c.name}" for t in project.tables for c in t.columns if c.generator == key]


# ---------------------------------------------------------------- dela med teamet

def export_data(include_rules: bool = True) -> dict:
    a = _load_all()
    data = {"generatorer": list(a["generator"].values()), "listor": a["list"]}
    if a["codebook"]:
        data["kodverk"] = a["codebook"]
    if a["testpnr"].get("lista"):
        data["testpersonnummer"] = a["testpnr"]["lista"]
    if include_rules:
        data["regler"] = rules.load_rules()
    return data


def export_yaml(include_rules: bool = True) -> str:
    return yaml.safe_dump(export_data(include_rules), allow_unicode=True, sort_keys=False)


def _parse(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Filen är inte ett generatorbibliotek.")
    gens = {}
    for g in data.get("generatorer") or []:
        if isinstance(g, dict) and str(g.get("key", "")).startswith(PREFIX) and g.get("kind") in ("table", "preset"):
            gens[g["key"]] = g
    lists = {k: v for k, v in (data.get("listor") or {}).items() if k in SPECS and isinstance(v, list)}
    for k, v in lists.items():
        from_rows(SPECS[k], v)  # kontrollera formatet
    codebooks = {k: v for k, v in (data.get("kodverk") or {}).items() if k in CODEBOOK_KINDS and isinstance(v, list)}
    pnr = [str(v) for v in data.get("testpersonnummer") or []]
    return {"generators": gens, "lists": lists, "rules": [r for r in data.get("regler") or [] if isinstance(r, dict)],
            "codebooks": codebooks, "test_pnr": pnr}


def import_yaml(text: str, include_rules: bool = True) -> dict[str, int]:
    """Läser in ett bibliotek. Generatorer och listor med samma nyckel ersätts; regler läggs till."""
    data = _parse(text)
    for key, defn in data["generators"].items():
        store.lib_put("generator", key, defn)
    for key, rows in data["lists"].items():
        store.lib_put("list", key, rows)
    for key, pairs in data["codebooks"].items():
        store.lib_put("codebook", key, pairs)
    if data["test_pnr"]:
        store.lib_put("testpnr", "lista", data["test_pnr"])
    n_rules = 0
    if include_rules and data["rules"]:
        current = rules.load_rules()
        have = {(r["pattern"], r.get("kind", "")) for r in current}
        new = [r for r in data["rules"] if (r.get("pattern"), r.get("kind", "")) not in have]
        if new:
            rules.save_rules(current + new)
            n_rules = len(new)
    refresh(force=True)
    out = {"generatorer": len(data["generators"]), "listor": len(data["lists"]), "regler": n_rules}
    if data["codebooks"]:
        out["kodverk"] = len(data["codebooks"])
    if data["test_pnr"]:
        out["testpersonnummer"] = len(data["test_pnr"])
    return out


def use_file(path: str | Path) -> None:
    """Lägger ett bibliotek från fil ovanpå det lokala, utan att spara (för kommandoraden)."""
    global _extra
    _extra = _parse(Path(path).read_text(encoding="utf-8"))
    refresh(force=True)


# ---------------------------------------------------------------- den gemensamma mappen

SHARED_FILE = "teamets_bibliotek.yaml"


def shared_dir() -> Path:
    """Mappen där teamets bibliotek delas: bibliotek/ i repot (ignoreras av git), eller DUMMYFILLER_SHARED."""
    env = os.environ.get("DUMMYFILLER_SHARED")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "bibliotek"


def _file_sig(path: Path) -> str:
    s = path.stat()
    return f"{s.st_mtime_ns}:{s.st_size}"


def shared_files() -> list[dict]:
    """Bibliotekfilerna i den gemensamma mappen och när de senast lästes in."""
    d = shared_dir()
    out = []
    for f in sorted(d.glob("*.y*ml")) if d.exists() else []:
        seen = (store.get_setting(f"shared:{f.name}") or "").split("|")
        out.append({"name": f.name, "path": f, "modified": datetime.fromtimestamp(f.stat().st_mtime), "imported": seen[0] == _file_sig(f)})
    return out


def sync_shared() -> list[tuple[str, dict]]:
    """Läser in nya eller ändrade filer i den gemensamma mappen. Teamets version ersätter det som har samma namn."""
    d = shared_dir()
    if not d.exists():
        return []
    done = []
    for f in sorted(d.glob("*.y*ml")):
        key, sig = f"shared:{f.name}", _file_sig(f)
        prev = (store.get_setting(key) or "|").split("|")
        if prev[0] == sig:
            continue
        text = f.read_text(encoding="utf-8")
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if prev[-1] != digest:
            try:
                done.append((f.name, import_yaml(text)))
            except Exception as e:
                done.append((f.name, {"fel": str(e)}))
                continue
        store.set_setting(key, f"{sig}|{digest}")
    return done


def publish(name: str = SHARED_FILE) -> Path:
    """Skriver hela det lokala biblioteket till den gemensamma mappen, så att det kan delas med kollegorna."""
    d = shared_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    text = export_yaml()
    path.write_text(text, encoding="utf-8")
    store.set_setting(f"shared:{name}", f"{_file_sig(path)}|{hashlib.sha1(text.encode('utf-8')).hexdigest()}")
    return path


def preview(defn: dict, n: int = 8, locale: str = "sv_SE") -> tuple[list[str], list[list], list[str]]:
    """Genererar några exempelvärden med en (ännu osparad) definition: (kolumner, rader, varningar)."""
    from .engine import generate
    from .model import Column, Project, Table

    key = PREFIX + "__preview__"
    REGISTRY[key] = make_spec(defn, key)
    try:
        if defn.get("kind") == "table":
            fields = table_fields(defn) or list(defn.get("columns") or [])
            cols = [Column.from_type(f, "nvarchar(400)", generator=key, params={"field": f}, manual=True) for f in dict.fromkeys(fields)]
        else:
            cols = [Column.from_type("Värde", "nvarchar(400)", generator=key, params={}, manual=True)]
        if not cols:
            return [], [], ["Tabellen har inga kolumner."]
        t = Table("Förhandsvisning", schema="", columns=cols, rows=n, category="other", category_manual=True)
        res = generate(Project(tables=[t], locale=locale), max_rows=n)
        d = res.data[t.key]
        return d.columns, d.rows, [w.split(": ", 1)[-1] for w in res.warnings]
    finally:
        REGISTRY.pop(key, None)
