"""Automatisk tolkning: tabellkategori, generator per kolumn och förslag på relationer.

Allt bygger på tabell-/kolumnnamn (svenska och engelska), datatyper och nycklar – ingen data hämtas.
"""
from __future__ import annotations

import re
from datetime import date

from . import care, library, region, rules, vocab
from .care import ICD_FORMATS
from .generators import CHOICE_MODES, NOTE_THEMES
from .model import Column, Project, Table

HIGH, LOW = "hög", "låg"


def norm(name: str) -> str:
    s = re.sub(r"([a-zåäö0-9])([A-ZÅÄÖ])", r"\1_\2", name)
    s = re.sub(r"([A-ZÅÄÖ]+)([A-ZÅÄÖ][a-zåäö])", r"\1_\2", s)
    s = s.lower().translate(str.maketrans("åäöéü", "aaoeu"))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


_PREFIXES = ("dim", "fact", "fakta", "stg", "tbl", "ref", "dw", "d", "f", "t")


def table_stem(name: str) -> tuple[str, str]:
    """Returnerar (prefix, kompakt namn utan prefix), t.ex. DimPatient -> ('dim', 'patient')."""
    toks = norm(name).split("_")
    prefix = toks[0] if len(toks) > 1 and toks[0] in _PREFIXES else ""
    return prefix, "".join(toks[1:] if prefix else toks)


class _N:
    """Namnmatchning mot en kolumn eller tabell."""

    def __init__(self, name: str):
        self.n = norm(name)
        self.toks = set(self.n.split("_"))
        self.c = self.n.replace("_", "")

    def sub(self, *words) -> bool:
        return any(w in self.c for w in words)

    def tok(self, *words) -> bool:
        return any(w in self.toks for w in words)

    def end(self, *words) -> bool:
        return self.c.endswith(words)


def _preset(name: str, ordered: bool = False):
    return "choice", {"values": "\n".join(vocab.PRESETS[name]), "mode": CHOICE_MODES[1 if ordered else 0]}


def _num(lo, hi, dist="Jämn", decimals=None, col: Column | None = None):
    if col is not None and col.kind == "int":
        return "number.int", {"min": int(lo), "max": int(hi), "distribution": dist}
    if decimals is None:
        decimals = col.scale if col is not None and col.scale is not None and col.kind == "decimal" else 2
    return "number.decimal", {"min": float(lo), "max": float(hi), "decimals": decimals, "distribution": dist}


SKEW, NORMAL = "Skev (många låga)", "Normal (flest i mitten)"
_START = ("start", "fran", "from", "borjan", "begin", "inskriv", "intag", "admission", "ankomst", "giltigfr", "validfr", "ordinationsdat", "insatt")
_END = ("slut", "end", "till", "tom", "upphor", "avslut", "utskriv", "discharge", "expire", "utgang", "validto", "giltigt", "utsatt")
_CREATED = ("skapad", "created", "registrerad", "insert", "upplagd", "regdatum")
_ORDERISH = ("faktura", "invoice", "bestall", "bokning", "remiss", "ordination", "ankomst", "registrer")
_UPDATED = ("andrad", "updated", "modified", "uppdaterad", "changed", "senast")
_DELIVERY = ("betald", "betalning", "paid", "forfall", "due", "svar", "besvarad", "attest")
_BIRTH = ("fodelse", "fodd", "birth")
_HIST_FROM = ("giltigfr", "validfr", "gallerfr", "effectivefr")
_HIST_TO = ("giltigt", "validto", "gallert", "effectiveto")
_CARE_WORDS = ("vard", "patient", "diagnos", "klinik", "besok", "remiss", "care", "encounter", "journal", "lakemedel", "ordination", "hsa")


def _find(table: Table, col: Column, words, kinds=("date", "datetime")) -> str | None:
    for c in table.columns:
        if c is not col and c.kind in kinds and not c.computed and _N(c.name).sub(*words):
            return c.name
    return None


def main_date(table: Table) -> Column | None:
    """Tabellens huvuddatum: första datumkolumnen som inte är slut-, ändrings-, betalnings- eller födelsedatum."""
    for c in table.columns:
        if c.kind in ("date", "datetime") and not c.computed and not _N(c.name).sub(*_END, *_UPDATED, *_DELIVERY, *_BIRTH, *_HIST_FROM):
            return c
    return None


def _ident(name: str) -> str:
    return name if name.isidentifier() else f"col('{name}')"


def _time_link(table: Table, project: Project | None):
    """Hur tabellens huvuddatum hänger ihop med en förälder: ('after', via, start, slut) eller ('chain', via, födelsedatum)."""
    if project is None:
        return None
    person = None
    for fk in table.foreign_keys:
        parent = project.table(fk.ref_table)
        if parent is None or parent.key == table.key or len(fk.columns) != 1:
            continue
        if parent.category == "transaction" and (start := main_date(parent)) is not None:
            end = next((c.name for c in parent.columns if c.kind in ("date", "datetime") and c is not start and _N(c.name).sub(*_END)), "")
            return "after", fk.columns[0], start.name, end
        if parent.category in ("person", "company") and person is None:
            birth = next((c.name for c in parent.columns if c.kind in ("date", "datetime") and _N(c.name).sub(*_BIRTH)), "")
            person = ("chain", fk.columns[0], birth, "")
    return person


def parse_checks(table: Table) -> dict[str, dict]:
    """Tolkar enkla CHECK-villkor: värdelistor (IN / OR) och intervall (>=, <=, BETWEEN) för en kolumn i taget."""
    out: dict[str, dict] = {}
    num = r"\(?\s*(-?\d+(?:\.\d+)?)\s*\)?"
    for expr in table.checks:
        cols = [c for c in table.columns if re.search(r"(?<![\w\]])\[?" + re.escape(c.name) + r"\]?(?![\w\[])", expr, re.I)]
        if len(cols) != 1:
            continue
        info = out.setdefault(cols[0].name, {})
        m = re.search(r"\bIN\s*\((.*)\)", expr, re.I | re.S)
        lits = None
        if m:
            lits = re.findall(r"N?'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?)", m.group(1))
        elif "=" in expr and not re.search(r"[<>]|\bAND\b|\bLIKE\b", expr, re.I):
            lits = re.findall(r"=\s*\(?\s*(?:N?'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?))", expr)
        if lits:
            info["values"] = [(a or b).replace("''", "'") for a, b in lits]
            continue
        b = re.search(r"\bBETWEEN\s*" + num + r"\s*AND\s*" + num, expr, re.I)
        if b:
            info["min"], info["max"] = float(b.group(1)), float(b.group(2))
        for op, val in re.findall(r"(>=|<=|>|<)\s*" + num, expr):
            step = 0 if "=" in op else (1 if cols[0].kind == "int" else 10 ** -(cols[0].scale or 2))
            if op.startswith(">"):
                info["min"] = max(info.get("min", float("-inf")), float(val) + step)
            else:
                info["max"] = min(info.get("max", float("inf")), float(val) - step)
    return out


def _default_literal(col: Column) -> str | None:
    """Standardvärdet om det är en konstant ('Aktiv', 0 …), annars None (t.ex. getdate())."""
    if not col.default:
        return None
    d = col.default.strip()
    while d.startswith("(") and d.endswith(")"):
        d = d[1:-1].strip()
    m = re.fullmatch(r"N?'((?:[^']|'')*)'", d)
    if m:
        return m.group(1).replace("''", "'")
    return d if re.fullmatch(r"-?\d+(?:\.\d+)?", d) else None


def date_column(table: Table) -> Column | None:
    dates = [c for c in table.columns if c.kind in ("date", "datetime") and not c.computed]
    for c in dates:
        if c.name in table.primary_key or _N(c.name).c in ("datum", "date", "dag", "day", "kalenderdatum", "fulldate"):
            return c
    return dates[0] if dates else None


# ---------------------------------------------------------------- tabellkategori

_CAL = ("kalender", "calendar", "datumdim", "dimdatum", "dimdate")
_REF_END = ("typ", "type", "typer", "status", "kategori", "category", "kod", "code", "koder", "grupp", "group", "klass", "niva", "kodverk", "lookup")
_TRANS = ("faktura", "invoice", "betalning", "payment", "transaktion", "transaction", "bokning", "booking", "handelse", "event",
          "logg", "vardkontakt", "besok", "visit", "encounter", "vardtillfalle", "admission", "remiss", "referral", "recept",
          "prescription", "ordination", "labsvar", "provsvar", "labresultat", "labbsvar", "labb", "journal", "arende", "ticket",
          "avtal", "kontrakt", "matning", "resultat", "budget", "utfall", "verifikat", "bokforing", "huvudbok", "reskontra",
          "franvaro", "loneutbetal", "lonetrans", "lonespec", "anstallning", "behandling", "attest", "bestallning", "tidbok")
_CODEISH = ("diagnos", "atgard", "lakemedel", "analys", "valuta", "currency", "sprak", "language", "kva", "icd", "atc",
            "konto", "ansvar", "kostnadsstalle", "verksamhet", "befattning", "franvaroorsak", "projekt")
_COMPANY = ("foretag", "company", "leverantor", "supplier", "vendor", "organisation", "organization", "bolag", "motpart", "kund", "customer")
_PERSON = ("person", "anstall", "employee", "medarbetare", "patient", "anvandare", "user", "kontakt", "contact", "personal",
           "lakare", "tandlakare", "vardgivare", "invanare", "medlem", "member", "elev", "student", "klient", "client")
_LOCATION = ("adress", "address", "ort", "plats", "location", "kontor", "office", "land", "country", "region", "kommun",
             "vardenhet", "klinik", "mottagning", "halsocentral", "vardcentral", "sjukhus", "avdelning", "enhet", "site", "fastighet")


def infer_category(table: Table) -> str:
    prefix, c = table_stem(table.name)
    n = _N(c)
    cols = [x for x in table.columns if not x.computed]
    fk_cols = {x for fk in table.foreign_keys for x in fk.columns}
    if len(table.foreign_keys) >= 2 and len(table.primary_key) >= 2 and set(table.primary_key) <= fk_cols:
        return "bridge"
    if (n.sub(*_CAL) or c in ("datum", "date", "tid", "time", "dag", "day")) and date_column(table) is not None:
        return "calendar"
    if prefix in ("fact", "fakta", "f"):
        return "transaction"
    if prefix == "ref" or c.endswith(_REF_END):
        return "reference"
    small = not table.foreign_keys and len(cols) <= 4
    if n.sub(*_TRANS):
        return "transaction"
    if n.sub(*_CODEISH):
        return "transaction" if table.foreign_keys else "reference"
    for words, cat in ((_PERSON, "person"), (_LOCATION, "location"), (_COMPANY, "company")):
        if n.sub(*words):
            return cat
    return "reference" if small else "other"


def default_rows(table: Table, project: Project | None = None) -> int:
    cat = table.category
    if cat == "reference":
        for c in table.columns:
            if c.generator == "choice" and str(c.params.get("mode", "")).startswith("I ordning"):
                return max(1, len([v for v in str(c.params.get("values", "")).splitlines() if v.strip()]))
            sizes = {"care.diagnosis": ("diagnosis", care.DIAGNOSES), "care.procedure": ("procedure", care.PROCEDURES),
                     "care.atc": ("drug", care.DRUGS), "care.drug": ("drug", care.DRUGS), "care.lab": ("lab", care.LABS)}
            for prefix, (kind, items) in sizes.items():
                if c.generator.startswith(prefix):
                    return care.codebook_size(project, kind, items) if project is not None else len(items)
            for prefix, size in region.sizes().items():
                if c.generator.startswith(prefix):
                    return size
            if (size := library.size_of(c.generator)) is not None:
                return size
        return 8
    if cat == "location":  # enhetstabeller: en rad per enhet
        for c in table.columns:
            for prefix in ("dental.clinic", "finance.cost_center"):
                if c.generator.startswith(prefix):
                    return region.sizes()[prefix]
            if (size := library.size_of(c.generator)) is not None:
                return size
    if cat == "transaction":
        lines = project is not None and any(
            (p := project.table(fk.ref_table)) is not None and p.category == "transaction" and p.key != table.key
            for fk in table.foreign_keys)
        return 6000 if lines else 2000
    return {"calendar": 1096, "person": 500, "company": 100, "location": 50, "bridge": 500}.get(cat, 200)


# ---------------------------------------------------------------- kolumner

def _reference_generator(table: Table, col: Column, n: _N):
    """Kodtabeller: välj värden utifrån tabellens namn, i ordning så att varje rad blir unik."""
    t = _N(table_stem(table.name)[1])
    is_code = n.sub("kod", "code") or (col.length is not None and col.length <= 3)
    special = [
        (("tandatgard", "tandvardsatgard", "tandbehandling"), "dental.procedure_code", "dental.procedure_text"),
        (("tanddiagnos",), "dental.diagnosis_code", "dental.diagnosis_text"),
        (("konto",), "finance.account_code", "finance.account_name"),
        (("ansvar", "kostnadsstalle"), "finance.cost_center_code", "finance.cost_center_name"),
        (("verksamhet",), "finance.activity_code", "finance.activity_name"),
        (("befattning", "yrkestitel"), "hr.title", "hr.title"),
        (("diagnos", "icd"), "care.diagnosis_code", "care.diagnosis_text"),
        (("atgard", "kva", "procedure"), "care.procedure_code", "care.procedure_text"),
        (("lakemedel", "atc", "drug"), "care.atc_code", "care.drug_name"),
        (("analys", "labtest"), "care.lab_name", "care.lab_name"),
    ]
    for words, code_gen, text_gen in special:
        if t.sub(*words):
            return (code_gen if is_code else text_gen), {}, HIGH
    presets = [
        (("fakturastatus", "attestatus", "atteststatus"), "invoice_status"), (("remisstatus", "remissstatus"), "care_referral_status"),
        (("bokningsstatus", "besoksstatus"), "care_booking_status"), (("status",), "status"),
        (("betalvillkor", "betalningsvillkor"), "payment_terms"), (("betal", "payment"), "payment"),
        (("prioritet", "priority"), "priority"), (("budgetversion", "budgettyp"), "budget_version"),
        (("leverantorstyp", "leverantorskategori"), "supplier_type"), (("franvaro",), "hr_absence"),
        (("anstallningsform",), "hr_employment_form"), (("forvaltning",), "hr_administration"),
        (("avdelning", "department"), "department"), (("roll", "role"), "role"), (("sprak", "language"), "language"),
        (("kontakttyp",), "care_contact_type"), (("besokstyp",), "care_visit_type"), (("vardform",), "care_form"),
        (("yrke", "profession"), "care_profession"), (("triage",), "care_triage"), (("diagnostyp",), "care_diagnosis_type"),
        (("patienttyp",), "dental_patient_type"), (("kategori", "category"), "category"),
    ]
    for words, name in presets:
        if t.sub(*words):
            return (*_preset(name, ordered=True), HIGH)
    for words, name in ((("valuta", "currency"), "currency"), (("land", "country"), "country")):
        if t.sub(*words):
            return (*_preset(name + "_code" if is_code else name, ordered=True), HIGH)
    if is_code:
        width = min(col.length or 3, 4)
        return "pattern", {"template": "{seq:0%d}" % width}, LOW
    return "pattern", {"template": f"{table.name} {{seq}}"}, LOW


def infer_column(col: Column, table: Table, project: Project | None = None) -> tuple[str, dict, str, float]:
    """Returnerar (generator, parametrar, säkerhet, andel NULL i %)."""
    n = _N(col.name)
    is_fk = table.fk_for(col.name) is not None
    if not col.computed and not is_fk:
        rule = rules.match_rule([n.c, n.n, col.name.lower()], col.kind)  # egna regler går före de inbyggda
        if rule:
            return rule["generator"], dict(rule.get("params") or {}), HIGH, float(rule.get("null_pct") or 0.0)
    gen, params, conf = _infer(col, table, project)
    check = parse_checks(table).get(col.name) if table.checks and not is_fk and not col.computed else None
    literal = _default_literal(col)
    if check and check.get("values"):
        vals = check["values"]
        weights = [60 if v == literal else max(1, round(40 / max(len(vals) - 1, 1))) for v in vals] if literal in vals else [1] * len(vals)
        gen, params, conf = "choice", {"values": "\n".join(f"{v} | {w}" for v, w in zip(vals, weights)), "mode": CHOICE_MODES[0]}, HIGH
    elif check and gen in ("number.int", "number.decimal"):
        lo, hi = check.get("min", float("-inf")), check.get("max", float("inf"))
        cast = int if gen == "number.int" else float
        if lo != float("-inf"):
            params["min"] = cast(max(params["min"], lo))
            params["max"] = cast(max(params["max"], params["min"]))
        if hi != float("inf"):
            params["max"] = cast(min(params["max"], hi))
            params["min"] = cast(min(params["min"], params["max"]))
        conf = HIGH
    elif gen == "bool" and conf == LOW and literal in ("0", "1"):
        params, conf = {"true_pct": 90.0 if literal == "1" else 10.0}, HIGH
    null_pct = 0.0
    if col.nullable and col.name not in table.primary_key:
        if gen == "date.relative" and n.sub(*_END):
            null_pct = 30.0
        elif gen in ("text.note", "text.lorem"):
            null_pct = 50.0
    return gen, params, conf, null_pct


def _infer(col: Column, table: Table, project: Project | None = None, _as_plain: bool = False) -> tuple[str, dict, str]:
    n, k, cat = _N(col.name), col.kind, table.category
    sub, tok, end = n.sub, n.tok, n.end
    tn = _N(table_stem(table.name)[1])
    single_pk = table.primary_key == [col.name]
    is_num = k in ("int", "decimal", "float")
    care_ctx = tn.sub(*_CARE_WORDS) or any(_N(c.name).sub(*_CARE_WORDS) for c in table.columns)

    if col.computed:
        return "", {}, HIGH
    if table.fk_for(col.name) is not None and not (cat == "calendar" and single_pk) and not _as_plain:
        # främmande nycklar fylls från föräldratabellen. Kodkolumner inom vård behåller sin generator, som då styr
        # vilken förälderrad som väljs (se ForeignKey.guided); övriga får bara en reserv om föräldern inte genereras.
        plain = _infer(col, table, project, True)
        if plain[0].startswith(region.GUIDED) and plain[2] == HIGH and not end("id", "key", "sk"):
            return plain
        if k == "int":
            return "number.int", {"min": 1, "max": 1000, "distribution": "Jämn"}, HIGH
        if k == "string":
            return "pattern", {"template": "{seq:0%d}" % min(col.length or 6, 6)}, HIGH
    if k == "uuid":
        return "uuid", {}, HIGH
    if k == "binary":
        return "null", {}, LOW

    # --- datumdimension
    if cat == "calendar":
        dc = date_column(table)
        if dc is col:
            return "date.sequence", {"start": "-3y", "step_days": 1}, HIGH
        if dc is not None:
            src = dc.name
            text = k == "string"
            part = None
            if k == "int" and (single_pk or tok("id", "key", "nyckel", "sk") or end("id", "key", "nyckel")):
                part = "Datumnyckel (ÅÅÅÅMMDD)"
            elif sub("manadsnamn", "monthname", "manadnamn"):
                part = "Månadsnamn"
            elif sub("veckodagsnamn", "dayname", "dagnamn"):
                part = "Veckodagsnamn"
            elif sub("kvartal", "quarter"):
                part = "Kvartalsnamn (Q1)" if text else "Kvartal"
            elif sub("armanad", "yearmonth", "manadar"):
                part = "År-månad (ÅÅÅÅ-MM)" if text else "ÅrMånad (ÅÅÅÅMM)"
            elif sub("dayofyear", "dagpaaret", "dagiar", "arsdag"):
                part = "Dag på året"
            elif sub("veckodag", "weekday", "dayofweek"):
                part = "Veckodagsnamn" if text else "Veckodag (1–7)"
            elif sub("vecka", "week"):
                part = "Vecka (ISO)"
            elif sub("manad", "month"):
                part = "Månadsnamn" if text else "Månad"
            elif sub("helg", "weekend"):
                part = "Helg (sant/falskt)"
            elif tok("ar", "year", "artal") or end("year", "artal"):
                part = "År"
            elif tok("dag", "day") or end("dag", "day"):
                part = "Dag"
            if part:
                return "date.part", {"source": src, "part": part}, HIGH

    # --- ekonomi: konto, ansvar, verksamhet, period (surrogatnycklar som KontoID hoppas över)
    codeish = is_num or sub("kod", "code", "nr", "nummer") or (col.length or 99) <= 8
    named = sub("namn", "benamning", "text", "name", "beskrivning")
    if not end("id", "key", "sk"):
        if sub("kontoklass", "accountclass"):
            return "finance.account_class", {}, HIGH
        if sub("kontonamn", "kontotext", "kontobenamning", "accountname"):
            return "finance.account_name", {}, HIGH
        if sub("kontonr", "kontonummer", "kontokod", "accountno", "accountcode") or n.c in ("konto", "account"):
            costs = tn.sub("leverantorsfaktura", "fakturarad", "inkop", "kostnad") and cat != "reference"
            return "finance.account_code", {"scope": region.ACCOUNT_SCOPES[1 if costs else 0]}, HIGH
        if sub("kostnadsstalle", "costcenter", "ansvarskod", "ansvarsnr", "ansvarsnamn", "ansvarsenhet") or tok("kst", "ansvar"):
            return ("finance.cost_center_name" if named or not codeish else "finance.cost_center_code"), {}, HIGH
        if sub("verksamhetskod", "verksamhetsnr", "verksamhetsnamn", "verksamhetsomrade") or tok("verksamhet", "vht"):
            return ("finance.activity_name" if named or not codeish else "finance.activity_code"), {}, HIGH
        if sub("forvaltning") and k == "string":
            return "finance.administration", {}, HIGH
        if (tok("period") or sub("bokforingsperiod", "redovisningsperiod", "periodkod")) and k in ("int", "string"):
            src = next((c.name for c in table.columns if c.kind in ("date", "datetime") and not c.computed and _N(c.name).sub("bokfor", "faktura", "verifikat", "transaktion", "utbetal")), "")
            fmt = "ÅÅÅÅ-MM" if k == "string" and (col.length or 9) >= 7 else "MM" if (col.length or 9) <= 2 or col.type_raw.lower().startswith("tinyint") else "ÅÅÅÅMM"
            return "finance.period", {"start": "-2y", "end": "idag", "format": fmt, "source": src}, HIGH
        if sub("ocr"):
            return "finance.ocr", {"digits": min(col.length or 12, 16)}, HIGH

    if single_pk and k == "int":
        return "sequence", {"start": 1, "step": 1}, HIGH

    # --- sant/falskt
    if k == "bool":
        if sub("inaktiv", "inactive", "raderad", "deleted", "sparr", "blocked", "makulerad", "avslutad", "avliden", "skyddad"):
            return "bool", {"true_pct": 5.0}, HIGH
        if sub("aktiv", "active", "current", "gallande", "giltig", "enabled", "aktuell"):
            return "bool", {"true_pct": 90.0}, HIGH
        return "bool", {"true_pct": 50.0}, LOW

    # --- datum och tid
    if k in ("date", "datetime"):
        if sub("fodelse", "fodd", "birth") or tok("dob"):
            return "person.birthdate", {"min_age": 0 if tn.sub("patient", "invanare") else 18, "max_age": 95 if care_ctx else 85}, HIGH
        if sub(*_END) and (base := _find(table, col, _START)):
            short = sub("utskriv", "discharge") or tn.sub("franvaro", "ledighet", "semester")
            kt = next((c.name for c in table.columns if _N(c.name).sub("kontakttyp", "encountertype")), None)
            if short and kt:  # vårdtiden beror på kontakttypen: besök avslutas samma dag, vårdtillfällen varar flera dagar
                b = _ident(base)
                return "expression", {"expr": f"{b} + days(slump(1, 12)) if {_ident(kt)} == 'Vårdtillfälle' else {b} + days(slump(0.01, 0.2))"}, HIGH
            return "date.relative", {"base": base, "min_days": 0 if short else 30, "max_days": 12 if short else 730}, HIGH
        if sub("andrad", "updated", "modified", "uppdaterad", "changed", "senast") and (base := _find(table, col, _CREATED)):
            return "date.relative", {"base": base, "min_days": 0, "max_days": 400}, HIGH
        status = next((c.name for c in table.columns if c.kind == "string" and _N(c.name).c in ("status", "fakturastatus")), None)
        if sub("betal", "paid") and col.nullable and status and (base := _find(table, col, _ORDERISH)):
            return "expression", {"expr": f"{_ident(base)} + days(int(slump(20, 45))) if {_ident(status)} == 'Betald' else None"}, HIGH
        if sub(*_DELIVERY) and (base := _find(table, col, _ORDERISH)):
            lo, hi = (30, 30) if sub("forfall", "due") else (20, 45) if sub("betal", "paid") else (1, 14)
            return "date.relative", {"base": base, "min_days": lo, "max_days": hi}, HIGH
        link = _time_link(table, project) if main_date(table) is col else None
        if link and link[0] == "after":
            return "date.after_parent", {"via": link[1], "column": link[2], "end_column": link[3], "min_days": 0, "max_days": 3}, HIGH
        if link and cat == "transaction":
            return "date.chain", {"via": link[1], "floor_column": link[2], "min_gap": 7, "max_gap": 180}, HIGH
        trend = "Ökande (fler mot slutet)" if cat == "transaction" else "Jämnt över perioden"
        return "date.between", {"start": "-3y", "end": "idag", "trend": trend}, HIGH if sub("datum", "date", "tid", "time", *_CREATED, *_START) or tok("dt") else LOW
    if k == "time":
        return "time.random", {}, HIGH

    # --- tandvård
    dental_ctx = tn.sub("tand", "dental", "folktand") or any(_N(c.name).sub("tandnr", "tandnummer", "tooth", "tandyta") for c in table.columns)
    if sub("tandnr", "tandnummer", "toothno", "tandposition") or tok("tand", "tooth"):
        return "dental.tooth", {}, HIGH
    if sub("tandyta", "tandytor", "surface") or tok("yta", "ytor"):
        return "dental.surface", {}, HIGH
    if dental_ctx:
        if sub("atgard", "behandling", "procedure") and not sub("datum", "date"):
            return ("dental.procedure_code" if codeish and not named else "dental.procedure_text"), {}, HIGH
        if sub("diagnos") and not sub("diagnostyp"):
            return ("dental.diagnosis_code" if sub("kod", "code") or (col.length or 99) <= 8 else "dental.diagnosis_text"), {}, HIGH
        if sub("klinik", "clinic", "mottagning") and k == "string":
            return "dental.clinic", {}, HIGH
        if sub("patienttyp") and k == "string":
            birth = next((c.name for c in table.columns if c.kind in ("date", "datetime") and _N(c.name).sub(*_BIRTH)), None)
            if birth:  # patienttypen följer åldern
                return "expression", {"expr": f"'Barn och unga' if year(today()) - year({_ident(birth)}) < 24 else 'Vuxen'"}, HIGH
            return (*_preset("dental_patient_type"), HIGH)
        if is_num and sub("pris", "referenspris", "arvode", "belopp", "kostnad", "patientavgift"):
            return "dental.price", {}, HIGH

    # --- vård
    if sub("diagnostyp"):
        via = next((fk.columns[0] for fk in table.foreign_keys if project and (p := project.table(fk.ref_table)) and p.category == "transaction"), "")
        if via:  # första diagnosen per vårdkontakt är huvuddiagnos, övriga bidiagnoser
            return "choice", {"values": "Huvuddiagnos\nBidiagnos", "mode": CHOICE_MODES[2], "via": via}, HIGH
        return (*_preset("care_diagnosis_type"), HIGH)
    if sub("diagnoskod", "diagnoscode", "dxcode") or tok("icd", "icd10") or sub("icd10") or (sub("diagnos", "diagnosis") and (sub("kod", "code") or (col.length or 99) <= 8)):
        fmt = 1 if (col.length or 99) < 5 else 0
        return "care.diagnosis_code", {"format": ICD_FORMATS[fmt]}, HIGH
    if sub("diagnos", "diagnosis") and k == "string":
        return "care.diagnosis_text", {}, HIGH
    if tok("kva") or sub("kvakod", "atgardskod", "procedurecode", "opkod", "operationskod"):
        return "care.procedure_code", {}, HIGH
    if sub("atgard", "procedure") and k == "string":
        return ("care.procedure_code" if sub("kod", "code") else "care.procedure_text"), {}, HIGH
    if tok("atc") or sub("atckod", "atccode"):
        return "care.atc_code", {}, HIGH
    if sub("lakemedel", "substans", "medication", "preparat") or tok("drug"):
        return ("care.atc_code" if sub("kod", "code") else "care.drug_name"), {}, HIGH
    if sub("beredning", "dosageform", "lakemedelsform"):
        return "care.drug_form", {}, HIGH
    if sub("styrka", "strength") and k == "string":
        return "care.drug_strength", {}, HIGH
    if sub("hsaid", "hsa"):
        return "care.hsa_id", {}, HIGH
    if sub("vardenhet", "careunit", "mottagning", "vardcentral", "halsocentral"):
        return "care.unit_name", {}, HIGH
    if sub("klinik", "clinic") and k == "string":
        return "care.clinic", {}, HIGH
    if sub("sjukhus", "hospital") and k == "string":
        return "care.hospital", {}, HIGH
    if sub("vardform"):
        return "care.care_form", {}, HIGH
    if (tok("region") or sub("regionnamn", "landsting")) and k == "string":
        return "care.region", {}, HIGH
    lab_ctx = tn.sub("lab", "prov", "analys") or any(_N(c.name).sub("analys") for c in table.columns)
    if sub("analysnamn", "labtest", "provnamn") or (sub("analys") and k == "string"):
        return "care.lab_name", {}, HIGH
    if lab_ctx:
        if sub("referens", "reference") or tok("ref"):
            if sub("min", "lag", "low", "nedre"):
                return "care.lab_ref_low", {}, HIGH
            if sub("max", "hog", "high", "ovre"):
                return "care.lab_ref_high", {}, HIGH
            return "care.lab_ref_interval", {}, HIGH
        if sub("resultat", "provsvar", "matvarde", "labvarde", "result", "varde", "value", "svar"):
            return "care.lab_value", {}, HIGH
        if sub("enhet", "unit"):
            return "care.lab_unit", {}, HIGH
        if sub("flagga", "avvik", "abnormal", "flag"):
            return "care.lab_flag", {}, HIGH
    if k == "string":
        patient_fk = project is not None and any((pt := project.table(fk.ref_table)) is not None and pt.category == "person"
                                                 and pt.key != table.key for fk in table.foreign_keys)
        if patient_fk and sub("kontakttyp", "encountertype"):  # följer kontaktens orsak och patientens sjukdomar
            return "care.contact_type", {}, HIGH
        if patient_fk and sub("besokstyp", "visittype"):
            return "care.visit_type", {}, HIGH
        for words, name in ((("kontakttyp", "encountertype"), "care_contact_type"), (("besokstyp", "visittype"), "care_visit_type"),
                            (("yrkesroll", "profession", "vardgivarkategori"), "care_profession"),
                            (("triage",), "care_triage"), (("remisstatus", "remissstatus"), "care_referral_status"),
                            (("inskrivningssatt", "intagningssatt"), "care_admission"),
                            (("utskrivningssatt", "utskriventill", "utskrivningtill"), "care_discharge")):
            if sub(*words):
                return (*_preset(name), HIGH)

    # --- personal
    if k == "string":
        if sub("yrkeskategori", "yrkesgrupp", "personalkategori", "personalgrupp"):
            return "hr.category", {}, HIGH
        if sub("befattning", "jobtitle", "yrkestitel", "tjanstetitel", "yrke") or tok("titel"):
            return "hr.title", {}, HIGH
        if sub("anstallningsform", "anstform"):
            return "hr.employment_form", {}, HIGH
        if sub("franvaroorsak", "franvarotyp", "franvarokod"):
            return (*_preset("hr_absence"), HIGH)
        if sub("loneart"):
            return (*_preset("hr_pay_type"), HIGH)
    if is_num and sub("sysselsattningsgrad", "tjanstgoringsgrad", "anstallningsgrad", "omfattning"):
        return "hr.grade", {}, HIGH

    # --- person, företag, kontaktuppgifter
    if sub("personnummer", "personnr", "persnr", "socialsecurity") or tok("pnr", "ssn"):
        ln = col.length or (12 if "big" in col.type_raw.lower() else 10 if k == "int" else 13)
        fmt = "ÅÅÅÅMMDD-NNNN" if ln >= 13 else "ÅÅÅÅMMDDNNNN" if ln == 12 else "ÅÅMMDD-NNNN" if ln == 11 else "ÅÅMMDDNNNN"
        if k == "int":
            fmt = fmt.replace("-", "")
        return "person.personnummer", {"format": fmt}, HIGH
    if sub("orgnr", "organisationsnummer", "orgnummer", "organisationsnr", "momsregnr"):
        return "company.orgnr", {"dash": (col.length or 11) >= 11 and k == "string"}, HIGH
    if sub("fornamn", "firstname", "givenname", "tilltalsnamn"):
        return "person.first_name", {}, HIGH
    if sub("efternamn", "lastname", "surname", "familyname"):
        return "person.last_name", {}, HIGH
    if sub("epost", "email", "mejl") or tok("mail"):
        return ("company.email" if cat == "company" else "person.email"), {}, HIGH
    if sub("telefon", "mobil", "phone") or tok("tel", "tfn", "fax"):
        fmt = "0701234567" if (k == "int" or (col.length or 20) < 13) else "070-123 45 67"
        return "phone", {"format": fmt}, HIGH
    if tok("kon", "gender", "sex") or sub("konkod", "juridisktkon"):
        fmt = "M / K" if (col.length or 10) < 6 else "Man / Kvinna"
        return "person.gender", {"format": "1 / 2" if is_num else fmt}, HIGH
    if sub("anvandarnamn", "username", "login", "signatur"):
        return "person.username", {}, HIGH
    if sub("losenord", "password", "hash"):
        return "faker", {"method": "sha256", "args": ""}, HIGH
    if sub("ipadress", "ipaddress") or tok("ip"):
        return "internet.ipv4", {}, HIGH
    if sub("webb", "hemsida", "website", "homepage") or tok("url", "www"):
        return ("company.website" if cat == "company" else "internet.url"), {}, HIGH
    if sub("postnr", "postnummer", "postalcode", "postcode", "postkod") or tok("zip"):
        return "address.postcode", {}, HIGH
    if sub("postort", "bostadsort", "hemort", "ortsnamn", "cityname") or tok("ort", "stad", "city", "town"):
        return "address.city", {}, HIGH
    if sub("gatuadress", "street", "adressrad", "addressline", "utdelningsadress") or tok("adress", "address", "gata") or end("adress", "address"):
        return "address.street", {}, HIGH
    if sub("kommun", "municipality") and k == "string":
        return "address.municipality", {}, HIGH
    if (tok("lan", "county") or sub("lansnamn")) and k == "string":
        return "address.county", {}, HIGH
    if sub("landskod", "countrycode", "landkod"):
        return "address.country_code", {}, HIGH
    if (tok("land", "country") or sub("landsnamn", "countryname")) and k == "string":
        return "address.country", {}, HIGH
    if sub("latitud") or tok("lat"):
        return (*_num(55.3, 68.5, decimals=5), HIGH)
    if sub("longitud") or tok("lon", "long", "lng"):
        return (*_num(11.1, 23.9, decimals=5), HIGH)
    if sub("iban"):
        return "finance.iban", {}, HIGH
    if sub("bankgiro") or tok("bg"):
        return "finance.bankgiro", {}, HIGH

    # --- tal
    if is_num:
        if sub("alder") or tok("age"):
            return (*_num(0 if care_ctx else 18, 95 if care_ctx else 85, NORMAL, col=col), HIGH)
        if sub("patientavgift", "besoksavgift"):
            return (*_preset("care_fee"), HIGH)
        if sub("momssats", "vatrate", "skattesats", "taxrate"):
            return (*_preset("vat_rate"), HIGH)
        if tok("lon", "salary") or sub("manadslon", "grundlon", "heltidslon"):
            return "hr.salary", {}, HIGH
        if sub("arslon"):
            return (*_num(300000, 900000, NORMAL, decimals=0, col=col), HIGH)

        def numcol(*words, skip=()):
            for c in table.columns:
                cn = _N(c.name)
                if (c is not col and not c.computed and c.kind in ("int", "decimal", "float") and cn.sub(*words)
                        and not cn.sub("sats", "procent", *skip) and not cn.end("id", "key", "nr")
                        and c.name not in table.primary_key and table.fk_for(c.name) is None):
                    return c.name
            return None
        scale = col.scale if col.kind == "decimal" and col.scale is not None else 2
        if sub("utfall", "actual") and (bud := numcol("budget")):  # utfallet hamnar nära budgeten
            return "expression", {"expr": f"round({_ident(bud)} * slump(0.82, 1.18), {scale})"}, HIGH
        if sub("avvikelse", "differens") and (bud := numcol("budget")) and (utf := numcol("utfall")):
            return "expression", {"expr": f"{_ident(utf)} - {_ident(bud)}"}, HIGH
        if sub("moms", "vat") and (net := numcol("netto", "exklmoms", "exmoms", "beloppexkl")):
            return "expression", {"expr": f"round({_ident(net)} * 0.25, {scale})"}, HIGH
        if sub("brutto", "inklmoms", "totalbelopp", "fakturabelopp", "attbetala") and (net := numcol("netto", "exklmoms", "exmoms", "beloppexkl")) and (vat := numcol("moms", "vat", skip=("exkl", "inkl", "netto"))):
            return "expression", {"expr": f"{_ident(net)} + {_ident(vat)}"}, HIGH
        if sub("belopp", "amount", "budget", "utfall", "kostnad", "intakt", "netto", "prognos") and any(
                _N(c.name).sub("konto", "account") and not _N(c.name).end("id", "key") for c in table.columns):
            return "finance.amount", {"factor": 25.0 if tn.sub("budget", "prognos") else 1.0}, HIGH  # beloppet följer kontot på raden
        if sub("belopp", "amount") and any(_N(c.name).sub("loneart") for c in table.columns):
            return (*_num(500, 48000, SKEW, col=col), HIGH)
        if sub("pris", "price"):
            return (*_num(10, 2500, SKEW, col=col), HIGH)
        if sub("saldo", "balance"):
            return (*_num(0, 150000, SKEW, col=col), HIGH)
        if sub("rabatt", "discount"):
            return (*_num(0, 30, SKEW, col=col), HIGH)
        if sub("procent", "percent", "andel") or tok("pct"):
            return (*_num(0, 100, col=col), HIGH)
        if sub("belopp", "amount", "summa", "total", "kostnad", "cost", "avgift", "fee", "intakt", "budget", "utfall", "prognos", "netto", "brutto", "moms", "skatt"):
            return (*_num(50, 25000, SKEW, col=col), HIGH)
        if sub("antal", "quantity", "kvantitet", "count") or tok("qty"):
            return (*_num(1, 20, SKEW, col=col), HIGH)
        if sub("vikt", "weight"):
            return (*_num(40 if care_ctx else 0.1, 130 if care_ctx else 50, NORMAL if care_ctx else SKEW, col=col), HIGH)
        if sub("langd", "length", "hojd", "height", "bredd", "width", "djup"):
            return (*_num(150 if care_ctx else 1, 200 if care_ctx else 300, NORMAL if care_ctx else "Jämn", col=col), HIGH)
        if sub("vardtid", "vardagar", "lengthofstay"):
            return (*_num(1, 21, SKEW, col=col), HIGH)
        if tok("ar", "year", "artal") or end("year", "artal"):
            per = next((c.name for c in table.columns if c is not col and c.kind == "int" and _N(c.name).tok("period")
                        and not c.type_raw.lower().startswith("tinyint")), None)
            if per:  # perioden är ÅÅÅÅMM: året följer av den
                return "expression", {"expr": f"int({_ident(per)} / 100)"}, HIGH
            return "number.int", {"min": date.today().year - 8, "max": date.today().year, "distribution": "Jämn"}, HIGH
        if sub("manad", "month"):
            return "number.int", {"min": 1, "max": 12, "distribution": "Jämn"}, HIGH
        if sub("betyg", "rating", "score", "poang"):
            return (*_num(1, 5, col=col), HIGH)
        if sub("radnr", "radnummer", "linenumber", "lineno", "lopnr", "sekvens") and table.foreign_keys:
            parent_first = sorted(table.foreign_keys, key=lambda f: (p := project.table(f.ref_table) if project else None) is None or p.category != "transaction")
            return "sequence.per_parent", {"via": parent_first[0].columns[0], "start": 1}, HIGH
        if sub("prioritet", "priority", "sortering", "sortorder", "ordning", "radnr", "linenumber", "position"):
            return (*_num(1, 10, col=col), HIGH)
        if k == "int":
            return "number.int", {"min": 1, "max": 1000, "distribution": "Jämn"}, LOW
        return (*_num(0, 1000, col=col), LOW)

    # --- text: värdelistor
    if k == "string":
        if cat == "reference" and not sub("beskrivning", "description", "kommentar", "comment"):
            return _reference_generator(table, col, n)
        if sub("status", "tillstand") or tok("state"):
            if care_ctx and tn.sub("remiss"):
                return (*_preset("care_referral_status"), HIGH)
            if care_ctx and tn.sub("besok", "bokning", "kontakt", "visit"):
                return (*_preset("care_booking_status"), HIGH)
            if tn.sub("faktura", "invoice", "attest") or sub("attest", "faktura"):
                return (*_preset("invoice_status"), HIGH)
            return (*_preset("case_status" if cat == "transaction" else "status"), HIGH)
        simple = [
            (("betalvillkor", "betalningsvillkor", "paymentterms"), "payment_terms"),
            (("betalsatt", "betalningssatt", "paymentmethod", "paymenttype", "betalmetod"), "payment"),
            (("prioritet", "priority"), "priority"), (("budgetversion", "budgettyp"), "budget_version"),
            (("leverantorstyp", "leverantorskategori"), "supplier_type"),
            (("sprak", "language"), "language"), (("valutakod", "currencycode"), "currency_code"),
        ]
        for words, name in simple:
            if sub(*words):
                return (*_preset(name), HIGH)
        if sub("valuta", "currency"):
            return (*_preset("currency_code" if (col.length or 99) <= 5 else "currency"), HIGH)
        if sub("avdelning", "department"):
            return (*_preset("care_ward" if care_ctx else "department"), HIGH)
        if tok("roll", "role") or sub("anvandarroll", "userrole"):
            return (*_preset("role"), HIGH)
        if (tok("enhet") or sub("enhetsnamn", "organisationsenhet", "arbetsplats", "arbetsstalle")) and not care_ctx:
            return "finance.cost_center_name", {}, HIGH  # organisatorisk enhet
        if sub("kategori", "category"):
            return (*_preset("category"), LOW)

        # --- text: namn
        if sub("foretagsnamn", "companyname", "bolagsnamn", "firmanamn", "leverantorsnamn", "suppliername", "organisationsnamn") or tok("foretag", "company", "bolag", "firma", "tillverkare"):
            return "company.name", {}, HIGH
        if sub("fullname", "fullstandigtnamn", "personnamn", "patientnamn", "kontaktperson", "contactname", "employeename", "medarbetare",
               "handlaggare", "ansvarig", "attestant", "lakare", "vardgivare", "behandlare", "skapadav", "andradav", "createdby", "modifiedby"):
            if sub("skapadav", "andradav", "createdby", "modifiedby"):
                return "person.username", {"group": "audit"}, HIGH
            return "person.full_name", {"group": "" if cat == "person" else n.c[:12]}, HIGH
        if tok("namn", "name", "benamning") or end("namn", "name"):
            if cat == "person":
                return "person.full_name", {}, HIGH
            if cat == "company":
                return "company.name", {}, HIGH
            if tn.sub("vardenhet", "mottagning", "vardcentral", "halsocentral", "enhet") and care_ctx:
                return "care.unit_name", {}, HIGH
            if tn.sub("klinik"):
                return "care.clinic", {}, HIGH
            if tn.sub("sjukhus"):
                return "care.hospital", {}, HIGH
            return "pattern", {"template": f"{table.name} {{seq}}"}, LOW

        if sub("radtext", "fakturatext", "verifikationstext", "transaktionstext", "konteringstext") and any(c.generator.startswith("finance.account") for c in table.columns):
            return "finance.account_name", {}, HIGH  # radtexten beskriver det som konterats
        if sub("beskrivning", "description", "kommentar", "comment", "notering", "anteckning", "meddelande", "message", "fritext", "anmarkning") or tok("note", "notes", "text", "info"):
            if (col.length or 999) < 40:
                return "text.words", {"min": 1, "max": 3}, HIGH
            return "text.note", {"theme": NOTE_THEMES[1 if care_ctx else 0]}, HIGH

        # --- text: nummer och koder
        if sub("nummer", "number") or tok("nr", "no", "num") or end("nr"):
            stem = re.sub(r"(nummer|number|nr|no|num)$", "", n.c)[:3].upper() or "NR"
            length = col.length or 20
            if length >= len(stem) + 7:
                return "pattern", {"template": f"{stem}-{{seq:06}}"}, HIGH
            return "pattern", {"template": "{seq:0%d}" % min(length, 8)}, HIGH
        if sub("typ", "type", "klass", "class", "grupp", "group"):
            base = col.name
            return "choice", {"values": f"{base} A | 50\n{base} B | 30\n{base} C | 20", "mode": CHOICE_MODES[0]}, LOW
        if single_pk or sub("kod", "code") or tok("id", "key") or end("id"):
            length = col.length or 10
            if single_pk or length > 6:
                stem = table_stem(table.name)[1][:3].upper()
                if length >= len(stem) + 6:
                    return "pattern", {"template": f"{stem}{{seq:05}}"}, HIGH if single_pk else LOW
                return "pattern", {"template": "{seq:0%d}" % min(length, 8)}, HIGH if single_pk else LOW
            return "pattern", {"template": "?" * min(length, 2) + "#" * max(0, min(length, 4) - 2)}, LOW
        if (col.length or 99) <= 3:
            return "pattern", {"template": "?" * (col.length or 1)}, LOW
        return "text.words", {"min": 1, "max": 2}, LOW

    return "null", {}, LOW


# ---------------------------------------------------------------- tillämpning

def infer_table(table: Table, project: Project | None = None, force: bool = False, set_rows: bool = False) -> None:
    """Sätter kategori och generatorer. Kolumner som användaren själv ändrat lämnas orörda (om inte force)."""
    if not table.category_manual:
        table.category = infer_category(table)
    for col in table.columns:
        if col.manual and not force:
            continue
        col.generator, col.params, col.confidence, col.null_pct = infer_column(col, table, project)
        col.manual = False
    if not table.history:
        table.history = detect_history(table)
    if set_rows:
        table.rows = default_rows(table, project)
        default_fk_settings(table, project)


def detect_history(table: Table) -> dict:
    """Känner igen SCD2-tabeller på giltig från/till-kolumner. Slås på automatiskt om en 'aktuell'-flagga också finns."""
    def find(words, kinds):
        return next((c.name for c in table.columns if c.kind in kinds and not c.computed and _N(c.name).sub(*words)), "")
    f, t = find(_HIST_FROM, ("date", "datetime")), find(_HIST_TO, ("date", "datetime"))
    if not f or not t:
        return {}
    cur = find(("aktuell", "current", "gallande", "senaste"), ("bool", "int"))
    return {"enabled": bool(cur) or table_stem(table.name)[0] in ("dim", "d"), "from": f, "to": t, "current": cur,
            "min": 1, "max": 3, "changing": [], "open_end": "NULL"}


def default_fk_settings(table: Table, project: Project | None) -> None:
    """Rimliga utgångsvärden för nya relationer: rader per förälder för detaljtabeller, skev fördelning mot personer."""
    if project is None:
        return
    for fk in table.foreign_keys:  # kodkolumn (diagnos, läkemedel …) som pekar på en kodtabell: låt generatorn välja förälder
        parent = project.table(fk.ref_table)
        col = table.column(fk.columns[0]) if len(fk.columns) == 1 else None
        if parent is not None and parent.key != table.key and col is not None and col.generator.startswith(region.GUIDED):
            fk.guided = True
    if table.category not in ("transaction", "bridge"):
        return
    if table.category == "bridge":  # t.ex. 1–3 diagnoser per vårdkontakt
        for fk in table.foreign_keys:
            parent = project.table(fk.ref_table)
            if parent is not None and parent.category == "transaction" and fk.per_parent_max == 0:
                fk.per_parent_min, fk.per_parent_max = 1, 3
                return
        return
    driver = False
    tname = _N(table.name)
    lines = tname.sub("rad", "line", "detail", "item", "post")
    treat = tname.sub("behandling", "atgard")  # varje besök har minst en behandling
    for fk in table.foreign_keys:
        parent = project.table(fk.ref_table)
        if parent is None or parent.key == table.key:
            continue
        if parent.category == "transaction" and not driver and fk.per_parent_max == 0:
            fk.per_parent_min, fk.per_parent_max = (1, 5) if lines else (1, 3) if treat else (0, 3)
            driver = True
        elif parent.category == "person" and fk.distribution == "random" and any(c.generator == "person.birthdate" for c in parent.columns):
            fk.distribution = "need"  # patienter: äldre och kroniker får fler kontakter
        elif parent.category in ("person", "company") and fk.distribution == "random":
            fk.distribution = "skewed"  # några patienter/leverantörer står för många av händelserna


def infer_project(project: Project, tables: list[Table] | None = None, set_rows: bool = True) -> None:
    targets = tables if tables is not None else project.tables
    for t in targets:
        infer_table(t, project)
    for t in targets:  # andra varvet: datumlogik mellan tabeller kräver att alla kategorier är satta
        infer_table(t, project)
    if set_rows:
        for t in targets:  # efter att alla kategorier är satta (detaljrader beror på föräldern)
            t.rows = default_rows(t, project)
            default_fk_settings(t, project)


def suggest_relations(project: Project) -> list[tuple[str, str, str, str]]:
    """Föreslår relationer utifrån namn: Vardkontakt.PatientID -> Patient.PatientID, FactBudget.KontoKey -> DimKonto.KontoKey."""
    targets = []
    for t in project.tables:
        if len(t.primary_key) == 1 and (pk := t.column(t.primary_key[0])) is not None:
            stem = table_stem(t.name)[1]
            pkc = _N(pk.name).c
            names = {pkc} if pkc not in ("id", "key", "nyckel", "kod", "code") else set()
            names |= {stem + s for s in ("id", "key", "nyckel", "kod", "nr", "sk")}
            targets.append((t, pk, stem, names))
    out = []
    for t in project.tables:
        taken = {c for fk in t.foreign_keys for c in fk.columns}
        for col in t.columns:
            if col.name in taken or col.computed or t.primary_key == [col.name]:
                continue
            c = _N(col.name).c
            hits = [(pt, pk, stem) for pt, pk, stem, names in targets
                    if pt is not t and pk.kind == col.kind and (c in names or any(c.endswith(nm) and len(nm) > 4 for nm in names))]
            if len(hits) > 1:
                hits = [h for h in hits if h[2] and h[2] in c] or hits
            if len(hits) == 1:
                out.append((t.key, col.name, hits[0][0].key, hits[0][1].name))
    return out
