"""Lär generatorer från produktionsdata – lokalt, med hård spärr för personuppgifter.

Flöde:
1. analyse(): läser antal rader och ett slumpvist urval per tabell till minnet, och fördelningen av barn per förälder
   som aggregat direkt i databasen. Varje kolumn klassas: spärrad, skyddad, hoppas över eller lärs.
2. Det som lärs är bara aggregat: värden som förekommer minst k gånger, intervall utan extremvärden, säsongsprofiler,
   mönster för koder och samband mellan kolumner. Urvalet slängs när tabellen är analyserad.
3. apply(): blir generatorer i biblioteket och/eller inställningar på projektets kolumner.

Hård spärr (går inte att stänga av, och spärrade kolumner kan inte väljas):
- personnummer och samordningsnummer, e-post, telefonnummer, gatuadresser, personnamn, användarnamn, bankkonton och fritext –
  utifrån kolumnnamn, hur kolumnen tolkats och innehållet i urvalet;
- även i tillåtna kolumner tas enskilda värden bort om de ser ut som någon av dessa;
- födelsedatum är skyddade: bara åldersintervallet lärs.
Värden som förekommer färre än k gånger tas aldrig med (k är minst 5).

Kodtabeller (kategorin 'Referens / kodtabell', högst 5 000 rader) lärs i sin helhet som en uppslagstabell, eftersom de
innehåller regionens koder snarare än uppgifter om personer. Samma spärrar gäller för deras kolumner.
"""
from __future__ import annotations

import getpass
import importlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import sqlalchemy as sa

from . import library, store
from .generators import luhn_digit
from .inference import _N
from .model import Project, Table

K_MIN = 5
CODE_TABLE_MAX = 5000
LEARNED = "lärs"
BLOCKED = "spärrad"
PROTECTED = "skyddad"
SKIPPED = "hoppas över"

# ---------------------------------------------------------------- igenkänning av personuppgifter

_NAME_LOCALES = ["sv_SE", "no_NO", "da_DK", "fi_FI", "is_IS", "de_DE", "en_US", "en_GB", "pl_PL", "tr_TR", "nl_NL", "fr_FR", "es_ES",
                 "it_IT", "pt_PT", "et_EE", "lt_LT", "lv_LV", "cs_CZ", "hr_HR", "ro_RO", "hu_HU", "sk_SK", "sl_SI", "az_AZ", "id_ID", "sw",
                 "ha_NG", "ig_NG", "en_KE", "en_NG", "fr_DZ"]
_names_cache: tuple[set, set] | None = None


def name_lists() -> tuple[set, set]:
    """(förnamn, efternamn) i gemener, från Fakers inbyggda listor för många språk. Inget hämtas från internet."""
    global _names_cache
    if _names_cache is None:
        first, last = set(), set()

        def names(v):
            if isinstance(v, dict):
                v = v.keys()
            try:
                return [n.lower() for n in v if isinstance(n, str)]
            except TypeError:
                return []
        for loc in _NAME_LOCALES:
            try:
                prov = importlib.import_module(f"faker.providers.person.{loc}").Provider
            except Exception:
                continue
            for attr in ("first_names", "first_names_male", "first_names_female"):
                first.update(names(prov.__dict__.get(attr, getattr(prov, attr, None))))
            last.update(names(prov.__dict__.get("last_names", getattr(prov, "last_names", None))))
        _names_cache = (first, last)
    return _names_cache


_PNR = re.compile(r"^(?:\d{2})?(\d{2})(\d{2})(\d{2})[-+]?(\d{4})$")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}")
_STREET = re.compile(r"\b[a-zåäöéü]+(gatan|gata|vägen|väg|stigen|gränd|gränden|backen|torget|allén|leden|platsen|slingan|svängen|plan|road|street)"
                     r"\s+\d+", re.I)
_BOX = re.compile(r"^(box|pl|postbox)\s+\d+", re.I)
_TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ'\-]+")


def is_pnr(s: str) -> bool:
    """Personnummer eller samordningsnummer (10 eller 12 siffror, giltigt datum och kontrollsiffra)."""
    m = _PNR.match(s.replace(" ", ""))
    if not m:
        return False
    yy, mm, dd, last4 = m.groups()
    day = int(dd) - 60 if int(dd) > 60 else int(dd)
    if not (1 <= int(mm) <= 12 and 1 <= day <= 31):
        return False
    return luhn_digit(f"{yy}{mm}{dd}{last4[:3]}") == int(last4[3])


def is_phone(s: str) -> bool:
    d = re.sub(r"[\s\-()/]", "", s)
    return bool(re.fullmatch(r"(\+46|0046|0)\d{6,10}", d) or re.fullmatch(r"\+\d{8,14}", d))


def person_name(s: str) -> bool:
    """'Förnamn Efternamn' eller 'Efternamn, Förnamn'."""
    first, last = name_lists()
    toks = [t.lower() for t in _TOKEN.findall(s)]
    if len(toks) < 2 or len(toks) > 4 or any(ch.isdigit() for ch in s):
        return False
    if "," in s:  # Efternamn, Förnamn
        return toks[-1] in first and toks[0] in last | first
    return toks[0] in first and (toks[-1] in last or s.split()[-1][:1].isupper() and toks[-1] not in first)


def personal_value(v) -> str | None:
    """Skälet till att ett enskilt värde inte får följa med, eller None."""
    s = str(v).strip()
    if not s:
        return None
    if is_pnr(s) or (s.isdigit() and len(s) in (9, 11) and is_pnr(s.zfill(len(s) + 1))):
        return "personnummer"
    if _EMAIL.search(s):
        return "e-postadress"
    if is_phone(s):
        return "telefonnummer"
    if _STREET.search(s) or _BOX.match(s):
        return "adress"
    if person_name(s):
        return "personnamn"
    return None


# kolumnnamn som alltid spärras (jämförs utan versaler, understreck och å/ä/ö)
_BLOCK_NAMES = [
    (("personnummer", "personnr", "persnr", "samordningsnummer", "samordningsnr", "reservnummer", "socialsecurity"), ("pnr", "ssn"), "personnummer"),
    (("fornamn", "efternamn", "mellannamn", "tilltalsnamn", "fullname", "firstname", "lastname", "surname", "givenname", "familyname",
      "patientnamn", "personnamn", "kontaktperson", "contactname", "employeename", "medarbetarnamn", "handlaggare", "lakarnamn",
      "attestant", "behandlare", "forskrivare", "anhorig"), (), "personnamn"),
    (("anvandarnamn", "username", "login", "signatur", "skapadav", "andradav", "createdby", "modifiedby", "userid"), (), "användarnamn"),
    (("epost", "email", "mejl"), ("mail",), "e-postadress"),
    (("telefon", "mobil", "phone"), ("tel", "tfn", "fax"), "telefonnummer"),
    (("gatuadress", "adressrad", "addressline", "street", "postadress", "coadress", "utdelningsadress", "folkbokforingsadress"),
     ("adress", "address", "gata"), "adress"),
    (("iban", "bankkonto", "kontonummerbank", "clearingnummer", "personkonto"), (), "bankkonto"),
    (("ipadress", "ipaddress"), ("ip",), "IP-adress"),
    (("journaltext", "anteckning", "kommentar", "fritext", "anamnes", "epikris", "meddelande", "beskrivning", "notering", "anmarkning"), (), "fritext"),
]
_BLOCK_GENERATORS = {
    "person.first_name": "personnamn", "person.last_name": "personnamn", "person.full_name": "personnamn",
    "person.personnummer": "personnummer", "person.email": "e-postadress", "person.username": "användarnamn",
    "phone": "telefonnummer", "address.street": "adress", "address.full": "adress", "company.email": "e-postadress",
    "internet.ipv4": "IP-adress", "finance.iban": "bankkonto", "text.note": "fritext", "text.lorem": "fritext",
}


def _block_by_name(table: Table, name: str) -> str | None:
    n = _N(name)
    for subs, toks, reason in _BLOCK_NAMES:
        if reason == "fritext" and table.category == "reference":
            continue  # beskrivningar i kodtabeller prövas på innehållet i stället
        if n.sub(*subs) or (toks and n.tok(*toks)):
            return reason
    if table.category == "person" and (n.tok("namn", "name") or n.end("namn", "name")):
        return "personnamn"
    if table.category == "person" and n.sub("hsaid", "hsa"):
        return "personens HSA-id"
    return None


def classify(table: Table, col, values: list, prod_name: str | None = None) -> tuple[str, str] | None:
    """(status, skäl) för spärrade och skyddade kolumner, annars None. Prövas i tur och ordning: namn, tolkning, innehåll.

    Både projektets och produktionens kolumnnamn prövas, så att t.ex. Kod1 i projektet som heter PersonNr i produktionen spärras.
    """
    names = [col.name] + ([prod_name] if prod_name and prod_name != col.name else [])
    for name in names:
        n = _N(name)
        if col.generator == "person.birthdate" or n.sub("fodelsedat", "fodelsedag", "fodd", "birthdate", "dateofbirth") or n.tok("dob"):
            return PROTECTED, "födelsedatum – bara åldersintervallet lärs"
    for name in names:
        reason = _block_by_name(table, name)
        if reason:
            where = "kolumnens namn" if name == col.name else f"namnet i produktionen ({name})"
            return BLOCKED, f"{reason} ({where})"
    reason = _BLOCK_GENERATORS.get(col.generator)
    if reason:
        return BLOCKED, f"{reason} (kolumnens tolkning)"
    strs = [str(v).strip() for v in values if str(v).strip()]
    if not strs:
        return None
    total = len(strs)
    sample = strs if total <= 20000 else strs[:: max(1, total // 20000)]
    total = len(sample)
    hits = Counter()
    for s in sample:
        r = personal_value(s)
        if r:
            hits[r] += 1
    limits = {"personnummer": 0.05, "e-postadress": 0.05, "telefonnummer": 0.2, "adress": 0.2, "personnamn": 0.2}
    for r, share in limits.items():
        if hits[r] / total >= share:
            return BLOCKED, f"innehåller {r} ({hits[r] * 100 // total} % av värdena)"
    if col.kind == "string":
        first, last = name_lists()
        singles = [s.lower() for s in sample if " " not in s.strip()]
        distinct = len(set(sample))
        if singles and distinct > 20:
            share_first = sum(s in first for s in singles) / total
            share_last = sum(s in last for s in singles) / total
            if share_first >= 0.3 or share_last >= 0.3:
                return BLOCKED, "innehåller personnamn (förnamn eller efternamn)"
        lengths = [len(s) for s in sample]
        words = [len(s.split()) for s in sample]
        if (sum(lengths) / total > 40 or sum(words) / total > 5) and distinct / total > 0.3:
            return BLOCKED, "fritext (kan innehålla vad som helst)"
    return None


# ---------------------------------------------------------------- resultat

@dataclass
class Finding:
    table: str
    column: str
    type: str
    status: str
    reason: str = ""
    kind: str = ""  # choice, bool, histogram, date, pattern, conditional, birth, codetable
    defn: dict | None = None
    apply_params: dict = field(default_factory=dict)
    summary: str = ""
    null_pct: float | None = None
    dropped: int = 0


@dataclass
class TableResult:
    table: str
    rows: int = 0
    sampled: int = 0
    error: str = ""
    code_table: dict | None = None
    fanout: list = field(default_factory=list)


@dataclass
class LearnResult:
    meta: dict
    tables: list[TableResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    audit_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") if abs(x) >= 100 or float(x).is_integer() else f"{x:.2f}".replace(".", ",")


def _quantile(sorted_vals: list, q: float):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def _shape(s: str) -> str:
    return "".join("9" if ch.isdigit() else "A" if ch.isalpha() and ch.isupper() else "a" if ch.isalpha() else ch for ch in s)


def _preset(base: str, params: dict) -> dict:
    return {"kind": "preset", "base": base, "params": params}


# ---------------------------------------------------------------- analys per kolumn

def _analyse_values(table: Table, col, values: list, k: int, n_rows: int, prod_name: str | None = None) -> Finding:
    f = Finding(table.key, col.name, col.type_raw, SKIPPED)
    nonnull = [v for v in values if v is not None and not (isinstance(v, str) and not v.strip())]
    f.null_pct = round((n_rows - len(nonnull)) * 100 / n_rows, 1) if n_rows else None
    if col.name in table.primary_key or table.fk_for(col.name) is not None:
        f.reason = "nyckel – strukturen lärs via relationerna"
        return f
    if col.kind in ("binary", "uuid", "other", "time"):
        f.reason = "datatypen lärs inte"
        return f
    verdict = classify(table, col, nonnull, prod_name)
    if verdict and verdict[0] == BLOCKED:
        f.status, f.reason = verdict
        return f
    if len(nonnull) < k:
        f.reason = f"för få värden (färre än k = {k})"
        return f
    if verdict and verdict[0] == PROTECTED:  # födelsedatum: bara åldersintervallet
        today = date.today()
        ages = sorted((today - (v.date() if isinstance(v, datetime) else v)).days // 365 for v in nonnull if isinstance(v, (date, datetime)))
        if len(ages) < k:
            f.status, f.reason = PROTECTED, verdict[1]
            return f
        lo, hi = _quantile(ages, 0.01), _quantile(ages, 0.99)
        f.status, f.kind, f.reason = LEARNED, "birth", verdict[1]
        f.defn = _preset("person.birthdate", {"min_age": int(lo), "max_age": int(hi)})
        f.summary = f"ålder {lo}–{hi} år (P1–P99); inga enskilda datum"
        return f

    if col.kind == "bool":
        share = sum(bool(v) for v in nonnull) * 100 / len(nonnull)
        f.status, f.kind = LEARNED, "bool"
        f.defn = _preset("bool", {"true_pct": round(share, 1)})
        f.summary = f"sant i {share:.0f} %"
        return f

    if col.kind in ("date", "datetime"):
        ds = sorted(v for v in nonnull if isinstance(v, (date, datetime)))
        if len(ds) < k:
            f.reason = "för få datum"
            return f
        lo, hi = _quantile(ds, 0.005), _quantile(ds, 0.995)
        lo_d = lo.date() if isinstance(lo, datetime) else lo
        hi_d = hi.date() if isinstance(hi, datetime) else hi
        inside = [d for d in ds if lo <= d <= hi]
        months = Counter(f"{d.year}-{d.month:02d}" for d in inside)
        wd = Counter(d.weekday() for d in inside)
        hours = Counter(d.hour for d in inside if isinstance(d, datetime))
        params = {"start": lo_d.isoformat(), "end": hi_d.isoformat(),
                  "months": "\n".join(f"{m} | {c}" for m, c in sorted(months.items()) if c >= k),
                  "weekdays": ",".join(str(wd[i] if wd[i] >= k else 0) for i in range(7)),
                  "hours": ",".join(str(hours[h] if hours[h] >= k else 0) for h in range(24)) if col.kind == "datetime" and sum(hours.values()) else ""}
        if params["weekdays"] == "0,0,0,0,0,0,0":
            params["weekdays"] = "1,1,1,1,1,1,1"
        if params["hours"] and all(x == "0" for x in params["hours"].split(",")):
            params["hours"] = ""
        f.status, f.kind, f.defn = LEARNED, "date", _preset("date.profile", params)
        weekdays = sum(wd[i] for i in range(5)) * 100 / max(1, sum(wd.values()))
        top = months.most_common(1)[0][0] if months else ""
        f.summary = f"{lo_d:%Y-%m} – {hi_d:%Y-%m}, vardagar {weekdays:.0f} %" + (f", flest {top}" if top else "")
        return f

    # värden som får följa med: förekommer minst k gånger och ser inte ut som personuppgifter
    counts = Counter(str(v).strip() if isinstance(v, str) else v for v in nonnull)
    distinct = len(counts)
    is_num = col.kind in ("int", "decimal", "float")
    categorical = distinct <= (30 if is_num else 200)
    if categorical:
        kept, dropped_k, dropped_p = {}, 0, 0
        for v, c in counts.most_common():
            if c < k:
                dropped_k += c
            elif personal_value(v) or (isinstance(v, str) and "\n" in v):
                dropped_p += c
            else:
                kept[v] = c
        coverage = sum(kept.values()) / len(nonnull)
        if kept and (coverage >= 0.5 or is_num):
            f.status, f.kind = LEARNED, "choice"
            values_text = "\n".join(f"{_fmt(v) if is_num and not isinstance(v, int) else v} | {c}" for v, c in kept.items())
            f.defn = _preset("choice", {"values": values_text, "mode": "Slumpad (enligt vikt)"})
            f.dropped = dropped_k + dropped_p
            top = ", ".join(f"{v} {c * 100 / sum(kept.values()):.0f} %" for v, c in list(kept.items())[:4])
            f.summary = f"{len(kept)} värden: {top}" + (" …" if len(kept) > 4 else "")
            if dropped_p:
                f.summary += f" · {dropped_p} förekomster borttagna (liknar personuppgifter)"
            if dropped_k:
                f.summary += f" · {len(counts) - len(kept)} ovanliga värden utelämnade (k = {k})"
            f._kept = kept  # används för samband mellan kolumner, sparas inte
            return f

    if is_num:
        xs = sorted(float(v) for v in nonnull)
        lo, hi = _quantile(xs, 0.01), _quantile(xs, 0.99)
        inside = [x for x in xs if lo <= x <= hi]
        nbins = min(10, len(inside) // k)
        if nbins < 1 or lo is None:
            f.reason = "för få värden för en fördelning"
            return f
        edges = sorted(set(_quantile(inside, i / nbins) for i in range(nbins + 1)))
        if len(edges) < 2:
            edges = [lo, hi if hi > lo else lo + 1]
        bins = []
        for a, b in zip(edges, edges[1:]):
            c = sum(1 for x in inside if a <= x < b or (b == edges[-1] and x == b))
            if bins and c < k:  # för få i intervallet: slå ihop med föregående
                pa, _, pc = bins.pop()
                bins.append((pa, b, pc + c))
            else:
                bins.append((a, b, c))
        bins = [b for b in bins if b[2] >= k]
        if not bins:
            f.reason = "för få värden för en fördelning"
            return f
        dec = 0 if col.kind == "int" else (col.scale if col.scale is not None else 2)
        text = "\n".join(f"{round(a, dec):g};{round(b, dec):g} | {c}" for a, b, c in bins)
        f.status, f.kind, f.defn = LEARNED, "histogram", _preset("number.histogram", {"bins": text, "decimals": int(dec)})
        f.summary = f"{_fmt(lo)} – {_fmt(hi)} (P1–P99), median {_fmt(_quantile(inside, 0.5))}, {len(bins)} intervall"
        return f

    if col.kind == "string":  # koder och nummer: bara formen, aldrig värdena
        strs = [str(v).strip() for v in nonnull]
        shapes = Counter(_shape(s) for s in strs)
        shape, c = shapes.most_common(1)[0]
        if c / len(strs) < 0.5 or c < k or any(ch in shape for ch in "#?{}") or len(shape) > 40:
            f.reason = "varierande text utan gemensamt mönster"
            return f
        same = [s for s in strs if _shape(s) == shape]
        template = []
        for i, ch in enumerate(shape):
            col_chars = Counter(s[i] for s in same)
            top, tc = col_chars.most_common(1)[0]
            if ch == "9":
                template.append(top if tc / len(same) >= 0.99 else "#")
            elif ch in "Aa":
                template.append(top if tc / len(same) >= 0.95 else "?")
            else:
                template.append(ch)
        tpl = "".join(template)
        f.status, f.kind, f.defn = LEARNED, "pattern", _preset("pattern", {"template": tpl})
        f.summary = f"mönster {tpl} ({c * 100 // len(strs)} % av värdena); inga värden sparas"
        return f
    f.reason = "inget lämpligt mönster"
    return f


def _cramers_v(pairs: list[tuple], a_vals: list, b_vals: list) -> float:
    n = len(pairs)
    if n == 0 or len(a_vals) < 2 or len(b_vals) < 2:
        return 0.0
    joint = Counter(pairs)
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    chi2 = 0.0
    for a in a_vals:
        for b in b_vals:
            e = ca[a] * cb[b] / n
            if e > 0:
                chi2 += (joint[(a, b)] - e) ** 2 / e
    return math.sqrt(chi2 / (n * (min(len(a_vals), len(b_vals)) - 1)))


def _conditionals(table: Table, findings: dict, rows: list[dict], k: int) -> None:
    """Hittar kolumnpar där den ena styr den andra (t.ex. kontakttyp → vårdform) och gör om den beroende till 'choice.by'."""
    cats = [c.name for c in table.columns if c.name in findings and findings[c.name].kind == "choice" and len(getattr(findings[c.name], "_kept", {})) <= 30]
    order = {c.name: i for i, c in enumerate(table.columns)}
    candidates = []
    def safe(kept):  # värden som går att skriva i reglerna för 'choice.by'
        return all(not any(ch in str(v) for ch in ":,|\n") for v in kept)
    cats = [c for c in cats if safe(findings[c]._kept)]
    for i, a in enumerate(cats):
        for b in cats[i + 1:]:
            ka, kb = findings[a]._kept, findings[b]._kept
            pairs = [(r[a], r[b]) for r in rows if r.get(a) in ka and r.get(b) in kb]
            if len(pairs) < 5 * k:
                continue
            v = _cramers_v(pairs, list(ka), list(kb))
            if v >= 0.3:
                candidates.append((v, a, b, pairs))
    driven = set()
    for v, a, b, pairs in sorted(candidates, key=lambda x: -x[0]):
        a, b = (a, b) if order[a] < order[b] else (b, a)  # den tidigare kolumnen styr den senare
        if b in driven or a in driven:
            continue
        joint = Counter((x, y) if order[a] < order[b] else (y, x) for x, y in pairs)
        lines = []
        for av in findings[a]._kept:
            opts = [(bv, c) for (x, bv), c in joint.items() if x == av and c >= k]
            if opts:
                lines.append(f"{av}: " + ", ".join(f"{bv} | {c}" for bv, c in sorted(opts, key=lambda o: -o[1])))
        if not lines:
            continue
        lines.append("*: " + ", ".join(f"{bv} | {c}" for bv, c in findings[b]._kept.items()))
        fb = findings[b]
        fb.kind = "conditional"
        fb.defn = _preset("choice.by", {"mapping": "\n".join(lines)})
        fb.apply_params = {"column": a}
        fb.summary = f"beror på {a} (Cramérs V {v:.2f}) · " + fb.summary
        driven.add(b)


# ---------------------------------------------------------------- läsning från databasen

def _sample(conn, tbl: sa.Table, cols: list[str], rows: int, n: int) -> list[dict]:
    selected = [tbl.c[c] for c in cols]
    if rows <= n:
        q = sa.select(*selected)
    elif conn.dialect.name == "mssql":
        pct = min(100.0, max(0.01, n * 3 * 100 / rows))
        name = (f"[{tbl.schema}]." if tbl.schema else "") + f"[{tbl.name}]"
        collist = ", ".join(f"[{c}]" for c in cols)
        q = sa.text(f"SELECT TOP ({int(n)}) {collist} FROM {name} TABLESAMPLE SYSTEM ({pct:.4f} PERCENT) ORDER BY NEWID()")
    else:
        q = sa.select(*selected).order_by(sa.func.random()).limit(n)
    return [dict(zip(cols, r)) for r in conn.execute(q).all()]


def _fanout(conn, md, project: Project, table: Table, tbl: sa.Table, k: int, counts: dict, colmap: dict, where) -> list[dict]:
    """Antal barn per förälder, som aggregat i databasen. `where(nyckel)` ger produktionens (schema, tabell) för en projekttabell."""
    out = []
    for fk in table.foreign_keys:
        parent = project.table(fk.ref_table)
        if len(fk.columns) != 1 or parent is None or parent.key == table.key or parent.category in ("reference", "calendar"):
            continue
        prod_col = colmap.get(fk.columns[0]) or ""
        loc = where(parent.key)
        if prod_col not in tbl.c or loc is None:
            continue
        try:
            ptbl = sa.Table(loc[1], md, schema=loc[0] or None, autoload_with=conn)
        except sa.exc.NoSuchTableError:
            continue
        if parent.key not in counts:
            counts[parent.key] = conn.execute(sa.select(sa.func.count()).select_from(ptbl)).scalar() or 0
        col = tbl.c[prod_col]
        sub = sa.select(col.label("p"), sa.func.count().label("c")).where(col.isnot(None)).group_by(col).subquery()
        hist = {int(c): int(n) for c, n in conn.execute(sa.select(sub.c.c, sa.func.count()).group_by(sub.c.c)).all()}
        zero = max(0, counts[parent.key] - sum(hist.values()))
        if zero:
            hist[0] = zero
        hist = {c: n for c, n in hist.items() if n >= k}  # bara antal som minst k föräldrar har
        if not hist:
            continue
        expanded = sorted(c for c, n in hist.items() for _ in range(min(n, 10000)))
        lo, hi, med = _quantile(expanded, 0.05), _quantile(expanded, 0.95), _quantile(expanded, 0.5)
        out.append({"column": fk.columns[0], "parent": parent.key, "min": int(lo), "max": int(max(hi, lo)),
                    "summary": f"{lo}–{hi} per förälder (P5–P95), median {med}"})
    return out


def analyse(engine, project: Project, keys: list[str], k: int = 10, sample: int = 50000, progress=None, source: str = "",
            mapping: dict | None = None) -> LearnResult:
    """Läser från produktionsdatabasen och tar fram förslag. Bara aggregat lämnar funktionen.

    `mapping` (se matching.py) kopplar projektets tabeller och kolumner till produktionens när namnen skiljer sig. Utan
    koppling letas tabeller och kolumner upp med samma namn som i projektet.
    """
    from .engine import coerce
    from .model import parse_type

    def where(key: str):
        if mapping is None:
            t = project.table(key)
            return (t.schema, t.name) if t else None
        tm = (mapping.get("tables") or {}).get(key)
        return (tm.get("schema") or "", tm["name"]) if tm else None

    def colmap_of(t: Table) -> dict:
        if mapping is None:
            return {c.name: c.name for c in t.columns}
        cols = (mapping.get("columns") or {}).get(t.key) or {}
        return {c: v["name"] for c, v in cols.items()}
    k = max(K_MIN, int(k))
    sample = max(CODE_TABLE_MAX, int(sample))
    res = LearnResult(meta={"source": source, "k": k, "sample": sample, "at": datetime.now().isoformat(timespec="seconds"),
                            "user": getpass.getuser()})
    md = sa.MetaData()
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for i, key in enumerate(keys):
            t = project.table(key)
            if progress:
                progress(key, i, len(keys))
            tr = TableResult(key)
            res.tables.append(tr)
            loc = where(key)
            if loc is None:
                tr.error = "är inte matchad mot någon tabell i produktionen"
                continue
            try:
                tbl = sa.Table(loc[1], md, schema=loc[0] or None, autoload_with=conn)
            except sa.exc.NoSuchTableError:
                tr.error = f"{'.'.join(x for x in loc if x)} finns inte i produktionsdatabasen"
                continue
            colmap = {a: b for a, b in colmap_of(t).items() if b}
            cols = [c for c in t.columns if not c.computed and (colmap.get(c.name) or "") in tbl.c]
            missing = [c for c in t.columns if not c.computed and (colmap.get(c.name) or "") not in tbl.c]
            tr.rows = counts[key] = counts.get(key) or conn.execute(sa.select(sa.func.count()).select_from(tbl)).scalar() or 0
            raw = _sample(conn, tbl, [colmap[c.name] for c in cols], tr.rows, sample)
            rows = [{c.name: r[colmap[c.name]] for c in cols} for r in raw]  # produktionens namn -> projektets
            del raw
            for c in cols:  # olika datatyp i produktionen: tolka värdena som projektets typ
                try:
                    prod_kind = parse_type(str(tbl.c[colmap[c.name]].type))["kind"]
                except Exception:
                    prod_kind = c.kind
                if prod_kind != c.kind and not ({prod_kind, c.kind} <= {"int", "decimal", "float"}):
                    for r in rows:
                        r[c.name] = coerce(r[c.name], c)
            tr.sampled = len(rows)
            findings = {c.name: _analyse_values(t, c, [r[c.name] for r in rows], k, len(rows), colmap[c.name]) for c in cols}
            for c in missing:
                findings[c.name] = Finding(t.key, c.name, c.type_raw, SKIPPED, "saknar motsvarighet i produktionen")
            if t.category == "reference" and 0 < tr.rows <= CODE_TABLE_MAX and tr.sampled == tr.rows:
                _code_table(t, tr, findings, rows, cols)
            else:
                _conditionals(t, findings, rows, k)
            tr.fanout = _fanout(conn, md, project, t, tbl, k, counts, colmap, where)
            for c in cols + missing:
                f = findings[c.name]
                f.__dict__.pop("_kept", None)
                res.findings.append(f)
            del rows  # urvalet behövs inte längre
    res.audit_id = store.audit_add({
        "händelse": "analys", **res.meta, "tabeller": keys,
        "lärs": [f"{f.table}.{f.column}" for f in res.findings if f.status == LEARNED],
        "spärrade": {f"{f.table}.{f.column}": f.reason for f in res.findings if f.status in (BLOCKED, PROTECTED)},
    })
    return res


def _code_table(t: Table, tr: TableResult, findings: dict, rows: list[dict], cols) -> None:
    """Kodtabell: hela innehållet blir en uppslagstabell – utom spärrade kolumner."""
    allowed = [c.name for c in cols if findings[c.name].status not in (BLOCKED, PROTECTED) and c.kind not in ("binary", "uuid")]
    if not allowed:
        return
    seen, table_rows = set(), []
    for r in rows:
        row = []
        for c in allowed:
            v = r[c]
            if personal_value(v) if v is not None else False:
                v = None  # enskilda värden som ser ut som personuppgifter följer inte med
            row.append(v.isoformat() if isinstance(v, (date, datetime)) else (float(v) if hasattr(v, "as_tuple") else v))
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            table_rows.append(row)
    tr.code_table = {"kind": "table", "columns": allowed, "weight": "", "rows": table_rows}
    for c in allowed:
        f = findings[c]
        f.status, f.kind, f.reason, f.defn = LEARNED, "codetable", "", None
        f.apply_params = {"field": c}
        f.summary = f"ingår i uppslagstabellen för {t.name} ({len(table_rows)} rader)"


# ---------------------------------------------------------------- tillämpning

def gen_key(table: str, column: str | None = None) -> str:
    return library.PREFIX + "lard_" + library.slug(f"{table}_{column}" if column else table)


def apply(res: LearnResult, project: Project, chosen: set[tuple[str, str]], to_library: bool = True, to_project: bool = True,
          rows_factor: float | None = None, fanout: bool = True) -> dict[str, int]:
    """Gör förslagen till generatorer. Spärrade och skyddade kolumner utan förslag kan aldrig tillämpas."""
    when = res.meta.get("at", "")[:10]
    desc = f"Lärd från {res.meta.get('source') or 'produktion'} {when} · k = {res.meta.get('k')} · bara aggregat"
    defs: dict[str, dict] = {}
    done = Counter()
    by_table = {tr.table: tr for tr in res.tables}
    for f in res.findings:
        if f.status != LEARNED or (f.table, f.column) not in chosen:
            continue
        t = project.table(f.table)
        col = t.column(f.column) if t else None
        if col is None:
            continue
        if f.kind == "codetable":
            key = gen_key(t.name)
            if key not in defs:
                defs[key] = {**by_table[f.table].code_table, "key": key, "name": f"Lärd: {t.name}", "description": desc}
        else:
            key = gen_key(t.name, f.column)
            defs[key] = {**f.defn, "key": key, "name": f"Lärd: {t.name}.{f.column}", "description": f"{desc} · {f.summary}"}
        if to_project:
            col.generator, col.params, col.manual, col.confidence = key, dict(f.apply_params), True, ""
            if f.null_pct is not None and col.nullable and col.name not in t.primary_key:
                col.null_pct = f.null_pct
        done["kolumner"] += 1
    for key, defn in defs.items():
        if to_library:
            store.lib_put("generator", key, defn)
        project.custom_generators = {**(project.custom_generators or {}), key: defn}  # projektets kopia
    done["generatorer"] = len(defs)
    if to_project:
        for tr in res.tables:
            t = project.table(tr.table)
            if t is None or tr.error:
                continue
            if rows_factor is not None and tr.rows:
                t.rows = tr.rows if t.category == "reference" else max(1, round(tr.rows * rows_factor))
                done["radantal"] += 1
            if fanout:
                for fo in tr.fanout:
                    fk = t.fk_for(fo["column"])
                    if fk is not None and fo["max"] > 0:
                        fk.per_parent_min, fk.per_parent_max = fo["min"], fo["max"]
                        done["relationer"] += 1
    library.refresh(project, force=True)
    if res.audit_id:
        store.audit_update(res.audit_id, {"tillämpat": datetime.now().isoformat(timespec="seconds"), "generatorer": sorted(defs),
                                          "till_bibliotek": to_library, "till_projekt": to_project})
    return dict(done)
