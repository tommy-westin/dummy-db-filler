"""Generatorer: funktioner som skapar ett värde för en kolumn på en rad.

Varje generator registreras med en svensk etikett och en parameterlista som
webbgränssnittet använder för att bygga inställningsformulär automatiskt.
En generator anropas som func(ctx, p) där ctx är radens kontext (se engine.RowContext)
och p är kolumnens parametrar (standardvärden ifyllda).
"""
from __future__ import annotations

import ast
import json
import re
import statistics
import string
import unicodedata
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable

from . import vocab


@dataclass
class Param:
    name: str
    label: str
    type: str = "str"  # str | int | float | bool | select | text | column | list
    default: Any = ""
    options: list | None = None
    help: str = ""
    via: str = ""  # för typen parent_column: namnet på parametern som håller FK-kolumnen


@dataclass
class GenSpec:
    key: str
    label: str
    group: str
    func: Callable
    params: list[Param] = field(default_factory=list)
    help: str = ""


REGISTRY: dict[str, GenSpec] = {}
LIST_REVISION = 0  # ökas när de inbyggda listorna ändras (se library.py), så att cachar byggs om


def register(key: str, label: str, group: str, params: list[Param] | None = None, help: str = ""):
    def deco(func):
        REGISTRY[key] = GenSpec(key, label, group, func, list(params or []), help)
        return func
    return deco


def defaults(key: str) -> dict:
    spec = REGISTRY.get(key)
    return {p.name: p.default for p in spec.params} if spec else {}


def label_of(key: str) -> str:
    spec = REGISTRY.get(key)
    return f"{spec.group}: {spec.label}" if spec else key


LABEL_TO_KEY: dict[str, str] = {}


def _build_labels():
    LABEL_TO_KEY.clear()
    LABEL_TO_KEY.update({label_of(k): k for k in REGISTRY})


# ---------------------------------------------------------------- hjälpfunktioner

GROUP = Param("group", "Grupp", "str", "", help="Kolumner med samma grupp hör till samma person/företag/adress på raden. Ange t.ex. 'kontakt' om tabellen har två olika personer per rad.")


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def luhn_digit(digits: str) -> int:
    total = 0
    for i, ch in enumerate(digits):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10


def parse_date_spec(spec, today: date) -> date:
    """'2024-01-31', 'idag'/'today', eller relativt: '-3y', '+30d', '-6m', '-2v'."""
    s = str(spec).strip().lower()
    if s in ("", "today", "idag", "now", "nu"):
        return today
    m = re.fullmatch(r"([+-]?\d+)\s*(d|w|v|m|y|å)", s)
    if m:
        n = int(m.group(1))
        days = {"d": 1, "w": 7, "v": 7, "m": 30.44, "y": 365.25, "å": 365.25}[m.group(2)]
        return today + timedelta(days=round(n * days))
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise ValueError(f"Ogiltigt datum '{spec}'. Använd ÅÅÅÅ-MM-DD, 'idag' eller relativt, t.ex. -3y, -6m, +30d.")


DISTS = ["Jämn", "Normal (flest i mitten)", "Skev (många låga)"]


def _between(rng, lo: float, hi: float, dist: str) -> float:
    lo, hi = float(lo), float(hi)
    if hi < lo:
        lo, hi = hi, lo
    if dist.startswith("Normal"):
        return min(hi, max(lo, rng.gauss((lo + hi) / 2, (hi - lo) / 6)))
    if dist.startswith("Skev"):
        return lo + (hi - lo) * rng.betavariate(1.3, 5)
    return rng.uniform(lo, hi)


def _weighted(rng, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def _table_param(ctx, generator: str, group: str, name: str, default):
    for c in ctx.table.columns:
        if c.generator == generator and (c.params.get("group", "") or "") == group and name in c.params:
            return c.params[name]
    return default


# ---------------------------------------------------------------- entiteter (sammanhängande rader)

def person(ctx, group: str = "") -> dict:
    def build():
        rng, fake = ctx.rng, ctx.fake
        test = _test_pnr(ctx)
        if test:
            born, female, pnr4 = test
            first = getattr(fake, "first_name_female" if female else "first_name_male", fake.first_name)()
            return {"female": female, "first": first, "last": fake.last_name(), "born": born, "pnr4": pnr4,
                    "tag": rng.choice(["", "", "", str(rng.randint(1, 99))])}
        female = rng.random() < 0.5
        first = getattr(fake, "first_name_female" if female else "first_name_male", fake.first_name)()
        lo = int(_table_param(ctx, "person.birthdate", group, "min_age", 18))
        hi = int(_table_param(ctx, "person.birthdate", group, "max_age", 85))
        if hi < lo:
            lo, hi = hi, lo
        born = ctx.today - timedelta(days=rng.randint(lo * 365, hi * 365 + 364))
        serial = rng.randint(1, 99) * 10 + rng.choice([0, 2, 4, 6, 8] if female else [1, 3, 5, 7, 9])
        nine = f"{born:%y%m%d}{serial:03d}"
        return {"female": female, "first": first, "last": fake.last_name(), "born": born,
                "pnr4": f"{serial:03d}{luhn_digit(nine)}", "tag": rng.choice(["", "", "", str(rng.randint(1, 99))])}
    return ctx.entity("person:" + (group or ""), build)


def _test_pnr(ctx):
    """Hämtar nästa officiella testpersonnummer om projektet har en sådan lista. Födelsedatum och kön följer numret."""
    name = ctx.project.test_pnr_list
    vals = ctx.project.value_lists.get(name) if name else None
    if not vals:
        return None
    pool = ctx.shared.get("pnr_pool")
    if pool is None:  # tolka listan en gång per tabell; ogiltiga rader hoppas över
        pool = []
        for raw in vals:
            digits = "".join(ch for ch in raw if ch.isdigit())
            if len(digits) == 10:
                digits = ("20" if int(digits[:2]) <= ctx.today.year % 100 else "19") + digits
            if len(digits) != 12:
                continue
            day = int(digits[6:8])
            try:
                born = date(int(digits[:4]), int(digits[4:6]), day - 60 if day > 60 else day)  # samordningsnummer har dag + 60
            except ValueError:
                continue
            pool.append((born, int(digits[10]) % 2 == 0, digits[8:]))
        ctx.rng.shuffle(pool)
        ctx.shared["pnr_pool"] = pool
    if not pool:
        raise ValueError(f"värdelistan '{name}' innehåller inga giltiga personnummer (12 eller 10 siffror)")
    return pool[(ctx.index + ctx.offset) % len(pool)]


def company(ctx, group: str = "") -> dict:
    def build():
        rng = ctx.rng
        name = ctx.fake.company()
        nine = f"{rng.randint(556000, 559999)}{rng.randint(0, 999):03d}"
        return {"name": name, "orgnr": nine + str(luhn_digit(nine)), "slug": slug(name)[:24] or "foretag"}
    return ctx.entity("company:" + (group or ""), build)


def address(ctx, group: str = "") -> dict:
    def build():
        rng, fake = ctx.rng, ctx.fake
        if ctx.locale.lower().startswith("sv"):
            city, kommun, lan, prefixes, _ = _weighted(rng, vocab.SWEDISH_CITIES, [c[4] for c in vocab.SWEDISH_CITIES])
            return {"street": f"{fake.street_name()} {rng.randint(1, 120)}{rng.choice(['', '', '', '', ' A', ' B', ' C'])}",
                    "postcode": f"{rng.choice(prefixes)} {rng.randint(10, 99)}", "city": city,
                    "municipality": kommun, "county": lan, "country": "Sverige", "country_code": "SE"}
        county = getattr(fake, "state", None) or getattr(fake, "county", None)
        return {"street": fake.street_address(), "postcode": fake.postcode(), "city": fake.city(),
                "municipality": fake.city(), "county": county() if county else "",
                "country": fake.current_country(), "country_code": fake.current_country_code()}
    return ctx.entity("address:" + (group or ""), build)


# ---------------------------------------------------------------- nycklar och tekniska värden

@register("sequence", "Löpnummer", "Nycklar", [
    Param("start", "Startvärde", "int", 1, help="Höj värdet om tabellen redan innehåller rader."),
    Param("step", "Steg", "int", 1),
], help="1, 2, 3 … Unikt per rad – passar primärnycklar.")
def gen_sequence(ctx, p):
    return int(p["start"]) + (ctx.index + ctx.offset) * int(p["step"])


@register("uuid", "UUID / GUID", "Nycklar")
def gen_uuid(ctx, p):
    return str(_uuid.UUID(int=ctx.rng.getrandbits(128), version=4))


@register("pattern", "Mönster", "Nycklar", [
    Param("template", "Mall", "str", "{seq:06}", help="# = siffra, ? = versal, {seq} = löpnummer, {seq:06} = löpnummer med nollor, {Kolumnnamn} = värdet i en annan kolumn. Exempel: FAK-{seq:06} eller ??-####"),
], help="Bygger värden efter en mall, t.ex. fakturanummer, anställningsnummer eller koder.")
def gen_pattern(ctx, p):
    out = []
    for m in re.finditer(r"\{([^}]+)\}|#|\?|.", str(p["template"]), flags=re.S):
        tok = m.group(0)
        if m.group(1):
            name, _, fmt = m.group(1).partition(":")
            if name in ("seq", "row"):
                out.append(format(ctx.index + 1 + ctx.offset, fmt or "d"))
            else:
                v = ctx.get(name)
                out.append("" if v is None else str(v))
        elif tok == "#":
            out.append(str(ctx.rng.randint(0, 9)))
        elif tok == "?":
            out.append(ctx.rng.choice(string.ascii_uppercase))
        else:
            out.append(tok)
    return "".join(out)


@register("constant", "Fast värde", "Egna värden", [Param("value", "Värde", "str", "")])
def gen_constant(ctx, p):
    return p["value"]


@register("null", "Alltid NULL", "Egna värden")
def gen_null(ctx, p):
    return None


# ---------------------------------------------------------------- egna värden

def parse_choices(text) -> tuple[list[str], list[float]]:
    values, weights = [], []
    lines = text if isinstance(text, list) else str(text).splitlines()
    for line in lines:
        line = str(line).strip()
        if not line:
            continue
        val, sep, w = line.rpartition("|")
        try:
            weight = float(w.strip().replace(",", ".")) if sep else 1.0
        except ValueError:
            val, weight = line, 1.0
        values.append((val if sep else line).strip())
        weights.append(max(weight, 0.0))
    return values, weights


CHOICE_MODES = ["Slumpad (enligt vikt)", "I ordning (rad 1 får första värdet …)", "I ordning per förälder (förlopp)"]


@register("choice", "Egna värden med vikt", "Egna värden", [
    Param("values", "Värden", "text", "A | 50\nB | 30\nC | 20", help="Ett värde per rad. Lägg till ' | vikt' för att styra hur vanligt värdet är, t.ex. 'Aktiv | 80'."),
    Param("mode", "Läge", "select", CHOICE_MODES[0], CHOICE_MODES, help="'Per förälder' ger första värdet till förälderns första rad, nästa värde till nästa rad osv. Sista värdet upprepas. Exempel: Remiss, Nybesök, Återbesök."),
    Param("via", "Förälder (för läget per förälder)", "fk", ""),
], help="Välj bland dina egna värden. Vikten styr fördelningen.")
def gen_choice(ctx, p):
    cache = ctx.state.get("choice")
    if cache is None or cache[0] != p["values"]:
        cache = ctx.state["choice"] = (p["values"], *parse_choices(p["values"]))
    _, values, weights = cache
    if not values:
        return None
    if str(p["mode"]).startswith("I ordning per"):
        seq = ctx.parent_seq(p["via"])
        return values[min(seq, len(values) - 1)] if seq is not None else _weighted(ctx.rng, values, weights)
    if str(p["mode"]).startswith("I ordning") or sum(weights) <= 0:
        return values[ctx.index % len(values)]
    return _weighted(ctx.rng, values, weights)


LIST_MODES = ["Slumpa bland exemplen (behåller frekvensen)", "Slumpa – varje unikt värde lika ofta", "I ordning", "Härma mönstret (nya värden med samma form)"]


def _analyse_examples(vals: list[str]) -> dict:
    nums = []
    try:
        for v in vals:
            nums.append(float(v.replace(" ", "").replace(",", ".")))
    except ValueError:
        nums = None
    if nums:
        decimals = max((len(v.replace(",", ".").partition(".")[2]) for v in vals), default=0)
        return {"type": "num", "lo": min(nums), "hi": max(nums), "mean": statistics.fmean(nums),
                "sd": statistics.pstdev(nums), "decimals": decimals}
    try:
        dates = [date.fromisoformat(v.strip()[:10]) for v in vals]
        return {"type": "date", "lo": min(dates), "hi": max(dates)}
    except ValueError:
        return {"type": "shape"}


@register("list", "Värdelista / exempelfil", "Egna värden", [
    Param("list", "Värdelista", "list", "", help="Läs in text- eller CSV-filer under 'Värdelistor'."),
    Param("mode", "Läge", "select", LIST_MODES[0], LIST_MODES, help="'Härma mönstret' skapar nya värden: tal och datum hamnar inom exemplens spridning, koder som AB-1234 får samma form med nya tecken."),
    Param("linked", "Håll ihop rader från samma CSV-fil", "bool", False, help="Kolumner som hämtar från samma CSV-fil får värden från samma exempelrad, så att t.ex. postnummer och ort hör ihop."),
], help="Använder värden från en inläst exempelfil.")
def gen_list(ctx, p):
    name = p["list"]
    vals = ctx.project.value_lists.get(name) or []
    if not vals:
        raise ValueError(f"värdelistan '{name}' saknas eller är tom")
    mode = str(p["mode"])
    if p["linked"] and ":" in name and not mode.startswith("Härma"):
        idx = ctx.entity("list:" + name.split(":")[0], lambda: ctx.rng.randrange(10**9))
        return vals[idx % len(vals)]
    if mode.startswith("I ordning"):
        return vals[ctx.index % len(vals)]
    if mode.startswith("Slumpa –"):
        uniq = ctx.state.get("uniq")
        if uniq is None:
            uniq = ctx.state["uniq"] = list(dict.fromkeys(vals))
        return ctx.rng.choice(uniq)
    if mode.startswith("Härma"):
        info = ctx.state.get("info")
        if info is None:
            info = ctx.state["info"] = _analyse_examples(vals)
        rng = ctx.rng
        if info["type"] == "num":
            x = min(info["hi"], max(info["lo"], rng.gauss(info["mean"], info["sd"])))
            return int(round(x)) if info["decimals"] == 0 else round(x, info["decimals"])
        if info["type"] == "date":
            return info["lo"] + timedelta(days=rng.randint(0, (info["hi"] - info["lo"]).days))
        return "".join(
            str(rng.randint(0, 9)) if ch.isdigit() else rng.choice(string.ascii_uppercase) if ch.isalpha() and ch.isupper()
            else rng.choice(string.ascii_lowercase) if ch.isalpha() else ch
            for ch in rng.choice(vals))
    return ctx.rng.choice(vals)


# ---------------------------------------------------------------- person

@register("person.first_name", "Förnamn", "Person", [GROUP])
def gen_first(ctx, p):
    return person(ctx, p["group"])["first"]


@register("person.last_name", "Efternamn", "Person", [GROUP])
def gen_last(ctx, p):
    return person(ctx, p["group"])["last"]


@register("person.full_name", "Fullständigt namn", "Person", [GROUP])
def gen_full(ctx, p):
    e = person(ctx, p["group"])
    return f"{e['first']} {e['last']}"


GENDER_FORMATS = ["Man / Kvinna", "M / K", "M / F", "Male / Female", "1 / 2"]


@register("person.gender", "Kön", "Person", [Param("format", "Format", "select", GENDER_FORMATS[0], GENDER_FORMATS), GROUP])
def gen_gender(ctx, p):
    a, b = [x.strip() for x in str(p["format"]).split("/")]
    return b if person(ctx, p["group"])["female"] else a


@register("person.birthdate", "Födelsedatum", "Person", [
    Param("min_age", "Lägsta ålder", "int", 18), Param("max_age", "Högsta ålder", "int", 85), GROUP,
], help="Stämmer överens med personnumret på samma rad.")
def gen_birthdate(ctx, p):
    return person(ctx, p["group"])["born"]


PNR_FORMATS = ["ÅÅÅÅMMDD-NNNN", "ÅÅÅÅMMDDNNNN", "ÅÅMMDD-NNNN", "ÅÅMMDDNNNN"]


@register("person.personnummer", "Personnummer", "Person", [Param("format", "Format", "select", PNR_FORMATS[0], PNR_FORMATS), GROUP],
          help="Påhittat men korrekt uppbyggt (kontrollsiffra, kön och födelsedatum stämmer med övriga kolumner).")
def gen_pnr(ctx, p):
    e = person(ctx, p["group"])
    fmt = str(p["format"])
    d = f"{e['born']:%Y%m%d}" if fmt.startswith("ÅÅÅÅ") else f"{e['born']:%y%m%d}"
    return d + ("-" if "-" in fmt else "") + e["pnr4"]


@register("person.email", "E-postadress (person)", "Person", [
    Param("domains", "Domäner", "str", "example.com, example.org, example.net", help="Kommaseparerad lista. Standard är reserverade exempeldomäner så att testdata aldrig kan nå riktiga brevlådor."), GROUP,
])
def gen_email(ctx, p):
    e = person(ctx, p["group"])
    domains = [d.strip() for d in str(p["domains"]).split(",") if d.strip()] or ["example.com"]
    return f"{slug(e['first'])}.{slug(e['last'])}{e['tag']}@{ctx.rng.choice(domains)}"


@register("person.username", "Användarnamn", "Person", [GROUP])
def gen_username(ctx, p):
    e = person(ctx, p["group"])
    return f"{slug(e['first'])[:3]}{slug(e['last'])[:3]}{ctx.rng.randint(10, 99)}"


PHONE_FORMATS = ["070-123 45 67", "0701234567", "+46701234567"]


@register("phone", "Telefonnummer (mobil)", "Person", [Param("format", "Format", "select", PHONE_FORMATS[0], PHONE_FORMATS)])
def gen_phone(ctx, p):
    rng = ctx.rng
    a, b = rng.choice("02369"), f"{rng.randint(0, 9999999):07d}"
    fmt = str(p["format"])
    if fmt.startswith("+"):
        return f"+467{a}{b}"
    if "-" in fmt:
        return f"07{a}-{b[:3]} {b[3:5]} {b[5:]}"
    return f"07{a}{b}"


# ---------------------------------------------------------------- företag

@register("company.name", "Företagsnamn", "Företag", [GROUP])
def gen_company(ctx, p):
    return company(ctx, p["group"])["name"]


@register("company.orgnr", "Organisationsnummer", "Företag", [Param("dash", "Med bindestreck", "bool", True), GROUP])
def gen_orgnr(ctx, p):
    o = company(ctx, p["group"])["orgnr"]
    return f"{o[:6]}-{o[6:]}" if p["dash"] else o


@register("company.email", "E-postadress (företag)", "Företag", [GROUP])
def gen_company_email(ctx, p):
    return f"{ctx.rng.choice(['info', 'kontakt', 'faktura', 'ekonomi'])}@{company(ctx, p['group'])['slug']}.example.com"


@register("company.website", "Webbplats", "Företag", [GROUP])
def gen_website(ctx, p):
    return f"https://www.{company(ctx, p['group'])['slug']}.example.com"


# ---------------------------------------------------------------- adress

def _addr(key, label):
    @register(f"address.{key}", label, "Adress", [GROUP], help="Ort, postnummer, kommun och län hör ihop på raden.")
    def gen(ctx, p, _key=key):
        return address(ctx, p["group"])[_key]
    return gen


for _k, _l in [("street", "Gatuadress"), ("postcode", "Postnummer"), ("city", "Ort"), ("municipality", "Kommun"),
               ("county", "Län"), ("country", "Land"), ("country_code", "Landskod")]:
    _addr(_k, _l)


@register("address.full", "Fullständig adress", "Adress", [GROUP])
def gen_address_full(ctx, p):
    a = address(ctx, p["group"])
    return f"{a['street']}, {a['postcode']} {a['city']}"


# ---------------------------------------------------------------- tal

@register("number.int", "Heltal", "Tal", [
    Param("min", "Lägsta", "int", 1), Param("max", "Högsta", "int", 1000),
    Param("distribution", "Fördelning", "select", DISTS[0], DISTS),
])
def gen_int(ctx, p):
    return int(round(_between(ctx.rng, p["min"], p["max"], str(p["distribution"]))))


@register("number.decimal", "Decimaltal / belopp", "Tal", [
    Param("min", "Lägsta", "float", 0.0), Param("max", "Högsta", "float", 1000.0),
    Param("decimals", "Decimaler", "int", 2),
    Param("distribution", "Fördelning", "select", DISTS[0], DISTS),
])
def gen_decimal(ctx, p):
    return round(_between(ctx.rng, p["min"], p["max"], str(p["distribution"])), int(p["decimals"]))


@register("bool", "Sant / falskt", "Tal", [Param("true_pct", "Andel sant (%)", "float", 50.0)])
def gen_bool(ctx, p):
    return ctx.rng.random() * 100 < float(p["true_pct"])


# ---------------------------------------------------------------- datum

def _as_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _window(ctx, start, end, floor_via="", floor_column="") -> tuple[date, date]:
    """Datumintervall med hänsyn till förälderns datum och till inkrementella körningar."""
    a, b = parse_date_spec(start, ctx.today), parse_date_spec(end, ctx.today)
    if b < a:
        a, b = b, a
    if floor_via and floor_column and ctx.parent_ref(floor_via) is not None:
        floor = _as_date(ctx.parent_value(floor_via, floor_column))
        if floor and floor > a:
            a = floor
    if ctx.since and ctx.since > a:
        a = ctx.since
    return a, max(a, b)


TIME_MODES = ["Slumpad tid", "Kontorstid (08–17)", "Ingen tid (00:00)"]
TRENDS = ["Jämnt över perioden", "Ökande (fler mot slutet)"]


def _add_time(ctx, d: date, mode: str):
    if ctx.column.kind != "datetime" or mode.startswith("Ingen"):
        return d
    lo, hi = (8 * 3600, 17 * 3600) if mode.startswith("Kontor") else (0, 86399)
    return datetime.combine(d, time()) + timedelta(seconds=ctx.rng.randint(lo, hi))


@register("date.between", "Datum i intervall", "Datum", [
    Param("start", "Från", "str", "-3y", help="ÅÅÅÅ-MM-DD, 'idag' eller relativt: -3y, -6m, -2v, +30d"),
    Param("end", "Till", "str", "idag"),
    Param("trend", "Fördelning", "select", TRENDS[0], TRENDS),
    Param("weekdays_only", "Endast vardagar", "bool", False),
    Param("time", "Klockslag (för datetime)", "select", TIME_MODES[0], TIME_MODES),
    Param("floor_via", "Tidigast enligt förälder (främmande nyckel)", "fk", "", help="Valfritt: datumet hamnar aldrig före ett datum i föräldraraden, t.ex. patientens födelsedatum eller leverantörens registreringsdatum."),
    Param("floor_column", "Förälderns datumkolumn", "parent_column", "", via="floor_via"),
])
def gen_date_between(ctx, p):
    a, b = _window(ctx, p["start"], p["end"], p["floor_via"], p["floor_column"])
    u = ctx.rng.random()
    if str(p["trend"]).startswith("Ökande"):
        u = u ** 0.5
    d = a + timedelta(days=int(u * ((b - a).days + 1)) if b > a else 0)
    d = min(d, b)
    if p["weekdays_only"]:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return _add_time(ctx, d, str(p["time"]))


@register("date.sequence", "Datum i följd", "Datum", [
    Param("start", "Första datum", "str", "-3y"), Param("step_days", "Dagar mellan rader", "int", 1),
], help="Rad 1 får första datumet, rad 2 nästa osv. – passar datumdimensioner.")
def gen_date_sequence(ctx, p):
    return parse_date_spec(p["start"], ctx.today) + timedelta(days=ctx.index * int(p["step_days"]))


@register("date.relative", "Datum relativt annan kolumn", "Datum", [
    Param("base", "Utgå från kolumn", "column", ""),
    Param("min_days", "Minst antal dagar efter", "int", 1), Param("max_days", "Högst antal dagar efter", "int", 14, help="Negativa tal ger datum före baskolumnen."),
], help="T.ex. förfallodatum 30 dagar efter fakturadatum, eller slutdatum efter startdatum.")
def gen_date_relative(ctx, p):
    base = ctx.get(p["base"])
    if base is None:
        return None
    if isinstance(base, str):
        base = datetime.fromisoformat(base)
    lo, hi = sorted((int(p["min_days"]), int(p["max_days"])))
    out = base + timedelta(days=ctx.rng.randint(lo, hi))
    if isinstance(out, datetime) and ctx.column.kind == "datetime":
        out += timedelta(seconds=ctx.rng.randint(0, 3600 * 6))
    return out


DATE_PARTS = ["År", "Kvartal", "Kvartalsnamn (Q1)", "Månad", "Månadsnamn", "Dag", "Veckodag (1–7)", "Veckodagsnamn", "Vecka (ISO)",
              "Dag på året", "Datumnyckel (ÅÅÅÅMMDD)", "ÅrMånad (ÅÅÅÅMM)", "År-månad (ÅÅÅÅ-MM)", "Helg (sant/falskt)"]


@register("date.part", "Del av datum i annan kolumn", "Datum", [
    Param("source", "Datumkolumn", "column", ""), Param("part", "Del", "select", DATE_PARTS[0], DATE_PARTS),
], help="Härleder år, månad, veckodag m.m. från en datumkolumn på samma rad.")
def gen_date_part(ctx, p):
    d = ctx.get(p["source"])
    if d is None:
        return None
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    sv = ctx.locale.lower().startswith("sv")
    part = str(p["part"])
    q = (d.month - 1) // 3 + 1
    return {
        "År": d.year, "Kvartal": q, "Kvartalsnamn (Q1)": f"Q{q}", "Månad": d.month,
        "Månadsnamn": (vocab.MONTHS_SV if sv else vocab.MONTHS_EN)[d.month - 1], "Dag": d.day,
        "Veckodag (1–7)": d.isoweekday(), "Veckodagsnamn": (vocab.WEEKDAYS_SV if sv else vocab.WEEKDAYS_EN)[d.weekday()],
        "Vecka (ISO)": d.isocalendar()[1], "Dag på året": d.timetuple().tm_yday,
        "Datumnyckel (ÅÅÅÅMMDD)": d.year * 10000 + d.month * 100 + d.day, "ÅrMånad (ÅÅÅÅMM)": d.year * 100 + d.month,
        "År-månad (ÅÅÅÅ-MM)": f"{d.year}-{d.month:02d}", "Helg (sant/falskt)": d.weekday() >= 5,
    }[part]


@register("time.random", "Klockslag", "Datum", [Param("from_hour", "Från timme", "int", 7), Param("to_hour", "Till timme", "int", 19)])
def gen_time(ctx, p):
    lo, hi = sorted((int(p["from_hour"]), int(p["to_hour"])))
    s = ctx.rng.randint(lo * 3600, max(lo * 3600, min(hi * 3600, 86399)))
    return time(s // 3600, s % 3600 // 60, s % 60)


# ---------------------------------------------------------------- text

NOTE_THEMES = ["Administration (ekonomi, personal, ärenden)", "Vård (journalanteckning)"]


@register("text.note", "Anteckning (svensk mening)", "Text", [Param("theme", "Tema", "select", NOTE_THEMES[0], NOTE_THEMES)])
def gen_note(ctx, p):
    return ctx.rng.choice(care.CARE_NOTES if str(p["theme"]).startswith("Vård") else vocab.NOTES)


@register("text.words", "Ord", "Text", [Param("min", "Minst antal ord", "int", 1), Param("max", "Högst antal ord", "int", 2)])
def gen_words(ctx, p):
    lo, hi = sorted((int(p["min"]), int(p["max"])))
    return " ".join(ctx.rng.choice(vocab.WORDS) for _ in range(ctx.rng.randint(lo, hi))).capitalize()


@register("text.lorem", "Löptext (lorem ipsum)", "Text", [Param("sentences", "Antal meningar", "int", 3)])
def gen_lorem(ctx, p):
    return ctx.fake.paragraph(nb_sentences=int(p["sentences"]))


# ---------------------------------------------------------------- internet / ekonomi

@register("internet.url", "Webbadress", "Övrigt")
def gen_url(ctx, p):
    return f"https://www.example.com/{ctx.rng.choice(vocab.WORDS)}/{ctx.rng.randint(1, 9999)}"


@register("internet.ipv4", "IP-adress", "Övrigt")
def gen_ip(ctx, p):
    return ctx.fake.ipv4_private()


@register("finance.iban", "IBAN", "Övrigt")
def gen_iban(ctx, p):
    return ctx.fake.iban()


@register("finance.bankgiro", "Bankgironummer", "Övrigt")
def gen_bankgiro(ctx, p):
    return f"{ctx.rng.randint(100, 999)}-{ctx.rng.randint(1000, 9999)}"


@register("date.chain", "Datum i förlopp per förälder", "Datum", [
    Param("via", "Förälder (främmande nyckel)", "fk", ""),
    Param("start", "Första händelsen tidigast", "str", "-3y"), Param("end", "Senast", "str", "idag"),
    Param("min_gap", "Minst dagar till nästa händelse", "int", 7), Param("max_gap", "Högst dagar till nästa händelse", "int", 120),
    Param("floor_column", "Tidigast enligt förälderns datumkolumn", "parent_column", "", via="via", help="Valfritt, t.ex. födelsedatum."),
    Param("time", "Klockslag (för datetime)", "select", TIME_MODES[1], TIME_MODES),
], help="Rader med samma förälder bildar ett förlopp: första händelsen får ett slumpat datum, varje följande hamnar ett antal dagar efter den förra. Passar vårdkontakter per patient eller fakturor per leverantör.")
def gen_date_chain(ctx, p):
    a, b = _window(ctx, p["start"], p["end"], p["via"], p["floor_column"])
    ref = ctx.parent_ref(p["via"])
    last = ctx.state.setdefault("last", {})
    prev = last.get(ref[1]) if ref is not None else None
    if prev is None:
        d = a + timedelta(days=ctx.rng.randint(0, (b - a).days))
    else:
        lo, hi = sorted((int(p["min_gap"]), int(p["max_gap"])))
        base = max(_as_date(prev), a)
        d = base + timedelta(days=ctx.rng.randint(lo, hi))
        if d > b:  # förloppet når fram till periodens slut: resten trängs ihop i den tid som är kvar
            d = base + timedelta(days=ctx.rng.randint(0, max(0, (b - base).days)))
    value = _add_time(ctx, d, str(p["time"]))
    if isinstance(prev, datetime) and isinstance(value, datetime) and value <= prev:
        value = prev + timedelta(minutes=ctx.rng.randint(30, 240))
    if ref is not None:
        last[ref[1]] = value
    return value


@register("date.after_parent", "Datum efter eller inom förälderns datum", "Datum", [
    Param("via", "Förälder (främmande nyckel)", "fk", ""),
    Param("column", "Förälderns startdatum", "parent_column", "", via="via"),
    Param("end_column", "Förälderns slutdatum (valfritt)", "parent_column", "", via="via", help="Om angivet hamnar datumet mellan förälderns start- och slutdatum."),
    Param("min_days", "Minst dagar efter start", "int", 0), Param("max_days", "Högst dagar efter start", "int", 3, help="Används när slutdatum saknas."),
    Param("start", "Om föräldern saknas: från", "str", "-3y"), Param("end", "Om föräldern saknas: till", "str", "idag"),
    Param("time", "Klockslag (för datetime)", "select", TIME_MODES[0], TIME_MODES),
], help="Håller ihop tiden mellan tabeller: en fakturarad hamnar efter fakturadatum, ett provsvar inom vårdkontakten.")
def gen_date_after_parent(ctx, p):
    ref = ctx.parent_ref(p["via"])
    base = ctx.parent_value(p["via"], p["column"]) if ref is not None and p["column"] else None
    if base is None:
        a, b = _window(ctx, p["start"], p["end"])
        return _add_time(ctx, a + timedelta(days=ctx.rng.randint(0, (b - a).days)), str(p["time"]))
    if isinstance(base, str):
        base = datetime.fromisoformat(base)
    end = ctx.parent_value(p["via"], p["end_column"]) if p["end_column"] else None
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if end is not None and _as_date(end) >= _as_date(base):
        if isinstance(base, datetime) and isinstance(end, datetime) and ctx.column.kind == "datetime":
            return base + timedelta(seconds=ctx.rng.randint(0, max(0, int((end - base).total_seconds()))))
        return _as_date(base) + timedelta(days=ctx.rng.randint(0, (_as_date(end) - _as_date(base)).days))
    lo, hi = sorted((int(p["min_days"]), int(p["max_days"])))
    out = base + timedelta(days=ctx.rng.randint(lo, hi))
    if isinstance(out, datetime) and ctx.column.kind == "datetime":
        out += timedelta(seconds=ctx.rng.randint(0, 6 * 3600))
    return out


@register("sequence.per_parent", "Löpnummer per förälder", "Nycklar", [
    Param("via", "Förälder (främmande nyckel)", "fk", ""), Param("start", "Startvärde", "int", 1),
], help="1, 2, 3 … som börjar om för varje förälder – t.ex. radnummer på fakturarader.")
def gen_seq_per_parent(ctx, p):
    seq = ctx.parent_seq(p["via"])
    return int(p["start"]) + (seq if seq is not None else ctx.index)


@register("choice.by", "Egna värden beroende på annan kolumn", "Egna värden", [
    Param("column", "Styrande kolumn", "column", ""),
    Param("mapping", "Regler", "text", "Vårdtillfälle: Slutenvård\nBesök: Primärvård | 60, Specialiserad öppenvård | 40\n*: Primärvård",
          help="En rad per värde i den styrande kolumnen: 'värde: alternativ | vikt, alternativ | vikt'. Raden '*' gäller alla övriga värden."),
], help="Skapar samband mellan kolumner: vilka värden som är möjliga, och hur vanliga de är, beror på en annan kolumn på raden.")
def gen_choice_by(ctx, p):
    table = ctx.state.get("map")
    if table is None or ctx.state.get("src") != p["mapping"]:
        table = {}
        for line in str(p["mapping"]).splitlines():
            key, sep, rest = line.partition(":")
            if sep and rest.strip():
                table[key.strip().lower()] = parse_choices([x for x in rest.split(",")])
        ctx.state["map"], ctx.state["src"] = table, p["mapping"]
    v = ctx.get(p["column"])
    hit = table.get("" if v is None else str(v).strip().lower()) or table.get("*")
    if not hit or not hit[0]:
        return None
    return _weighted(ctx.rng, hit[0], hit[1]) if sum(hit[1]) > 0 else ctx.rng.choice(hit[0])


# ---------------------------------------------------------------- relationer och uttryck

@register("parent.lookup", "Kopiera värde från relaterad tabell", "Relation", [
    Param("via", "Via främmande nyckel (kolumn)", "fk", ""),
    Param("column", "Kolumn i föräldratabellen", "parent_column", "", via="via"),
], help="Hämtar ett värde från den förälderrad som främmande nyckeln pekar på – för denormaliserade kolumner, t.ex. leverantörsnamn på en order.")
def gen_parent_lookup(ctx, p):
    return ctx.parent_value(p["via"], p["column"])


@register("expression", "Formel", "Relation", [
    Param("expr", "Uttryck", "str", "", help="Räkna med andra kolumner på raden, t.ex. Antal * Belopp, round(Belopp * 0.25, 2), Startdatum + days(30) eller 'Ja' if Belopp > 1000 else 'Nej'. Funktioner: round, min, max, abs, int, float, str, len, upper, lower, concat, coalesce, days, year, month, today, slump(a, b), col('Kolumn med mellanslag')."),
])
def gen_expression(ctx, p):
    return evaluate(str(p["expr"]), ctx)


@register("faker", "Valfri Faker-metod", "Övrigt", [
    Param("method", "Metod", "str", "job", help="Namnet på en metod i biblioteket Faker, t.ex. job, license_plate, color_name, ean13, sha256, catch_phrase."),
    Param("args", "Argument (JSON)", "str", "", help='Valfritt, t.ex. {"length": 8}'),
])
def gen_faker(ctx, p):
    method = str(p["method"]).strip()
    if not method or method.startswith("_") or not hasattr(ctx.fake, method):
        raise ValueError(f"Faker saknar metoden '{method}'")
    kwargs = json.loads(p["args"]) if str(p["args"]).strip() else {}
    return getattr(ctx.fake, method)(**kwargs)


# ---------------------------------------------------------------- säker uttrycksmotor

_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Load,
            ast.Constant, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
_FUNC_NAMES = {"round", "min", "max", "abs", "int", "float", "str", "len", "upper", "lower", "concat", "coalesce",
               "days", "year", "month", "today", "slump", "col"}
_CODE_CACHE: dict[str, Any] = {}


def compile_expression(expr: str):
    code = _CODE_CACHE.get(expr)
    if code is None:
        if not expr.strip():
            raise ValueError("formeln är tom")
        tree = ast.parse(expr.strip(), mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED):
                raise ValueError(f"otillåtet i formel: {type(node).__name__}")
            if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNC_NAMES and not node.keywords):
                raise ValueError("endast de inbyggda funktionerna får anropas i formler")
        code = _CODE_CACHE[expr] = compile(tree, "<formel>", "eval")
    return code


class _Names(dict):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        val = self._value
        self.update({
            "round": round, "min": min, "max": max, "abs": abs, "int": int, "float": float, "str": str, "len": len,
            "upper": lambda s: str(s).upper(), "lower": lambda s: str(s).lower(),
            "concat": lambda *a: "".join("" if x is None else str(x) for x in a),
            "coalesce": lambda *a: next((x for x in a if x is not None), None),
            "days": lambda n: timedelta(days=n), "year": lambda d: d.year, "month": lambda d: d.month,
            "today": lambda: ctx.today, "slump": lambda a, b: ctx.rng.uniform(a, b), "col": val,
        })

    def _value(self, name):
        v = self.ctx.get(name)
        return float(v) if isinstance(v, Decimal) else v

    def __missing__(self, name):
        if self.ctx.has_column(name):
            return self._value(name)
        raise KeyError(name)


def evaluate(expr: str, ctx):
    return eval(compile_expression(expr), {"__builtins__": {}}, _Names(ctx))


from . import care  # noqa: E402,F401  (registrerar vårdgeneratorerna)
from . import region  # noqa: E402,F401  (ekonomi, personal, tandvård)

_build_labels()
