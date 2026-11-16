"""Vårddomänen: diagnoser, åtgärder, läkemedel, labbanalyser och vårdenheter.

Kodlistorna är ett litet urval exempel i samma format som ICD-10-SE, KVÅ och ATC –
inte kompletta kodverk. Behöver du fler koder: läs in en egen fil under 'Värdelistor'.
I tabeller med kategorin 'Referens / kodtabell' delas koderna ut i ordning (en per rad),
annars slumpas de så att vanliga koder förekommer oftare.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime

from . import generators as _g
from . import vocab
from .generators import GROUP, Param, _weighted, address, register

# (kod, text, vikt)
DIAGNOSES = [
    ("I10.9", "Essentiell hypertoni", 30), ("E11.9", "Diabetes mellitus typ 2 utan komplikationer", 22),
    ("J06.9", "Akut övre luftvägsinfektion, ospecificerad", 24), ("M54.5", "Lumbago", 16),
    ("N39.0", "Urinvägsinfektion, utan angiven lokalisation", 15), ("F32.9", "Depressiv episod, ospecificerad", 14),
    ("F41.9", "Ångesttillstånd, ospecificerat", 12), ("R07.4", "Bröstsmärtor, ospecificerade", 12),
    ("R10.4", "Andra och icke specificerade smärtor i buken", 12), ("I48.9", "Förmaksflimmer och förmaksfladder, ospecificerat", 11),
    ("J45.9", "Astma, ospecificerad", 10), ("J44.9", "Kroniskt obstruktiv lungsjukdom, ospecificerad", 9),
    ("I50.9", "Hjärtsvikt, ospecificerad", 9), ("J18.9", "Pneumoni, ospecificerad", 9),
    ("E78.0", "Ren hyperkolesterolemi", 8), ("E03.9", "Hypotyreos, ospecificerad", 8),
    ("M17.9", "Gonartros, ospecificerad", 8), ("M16.9", "Koxartros, ospecificerad", 6),
    ("I25.9", "Kronisk ischemisk hjärtsjukdom, ospecificerad", 7), ("I21.9", "Akut hjärtinfarkt, ospecificerad", 5),
    ("I63.9", "Cerebral infarkt, ospecificerad", 5), ("E10.9", "Diabetes mellitus typ 1 utan komplikationer", 4),
    ("G43.9", "Migrän, ospecificerad", 6), ("F43.9", "Reaktion på svår stress, ospecificerad", 7),
    ("K21.9", "Gastroesofageal refluxsjukdom utan esofagit", 6), ("K35.8", "Akut appendicit, annan och ospecificerad", 3),
    ("K80.2", "Gallsten utan kolecystit", 4), ("N20.0", "Njursten", 3),
    ("S52.5", "Fraktur på nedre delen av radius", 5), ("S72.0", "Fraktur på lårbenshalsen", 4),
    ("S06.0", "Hjärnskakning", 4), ("S82.6", "Fraktur på laterala malleolen", 3),
    ("C50.9", "Malign tumör i bröstkörtel, ospecificerad", 3), ("C61.9", "Malign tumör i prostata", 3),
    ("C34.9", "Malign tumör i bronk eller lunga, ospecificerad", 2), ("H25.9", "Senil katarakt, ospecificerad", 5),
    ("H66.9", "Mellanöreinflammation, ospecificerad", 6), ("L40.9", "Psoriasis, ospecificerad", 3),
    ("D50.9", "Järnbristanemi, ospecificerad", 4), ("A09.9", "Gastroenterit och kolit av ospecificerad orsak", 6),
    ("B34.9", "Virusinfektion, ospecificerad", 8), ("R51.9", "Huvudvärk", 7),
    ("Z00.0", "Allmän medicinsk undersökning", 8), ("U07.1", "Covid-19, virus identifierat", 5),
]

PROCEDURES = [
    ("NFB29", "Primär total höftledsplastik utan cement", 8), ("NFB49", "Primär total höftledsplastik med cement", 8),
    ("NGB49", "Primär total knäledsplastik med cement", 10), ("JEA01", "Laparoskopisk appendektomi", 8),
    ("JEA00", "Appendektomi", 3), ("JKA21", "Laparoskopisk kolecystektomi", 9),
    ("FNG05", "Perkutan koronar intervention (PCI) med stent", 8), ("FNG02", "Perkutan koronar intervention (PCI)", 4),
    ("CJE20", "Fakoemulsifikation med implantation av bakre kammarlins", 16), ("MCA10", "Kejsarsnitt", 7),
    ("UJD02", "Gastroskopi", 12), ("UJF32", "Koloskopi", 12), ("EMB10", "Tonsillektomi", 5),
    ("JAB30", "Operation för ljumskbråck med nät", 7), ("LCD00", "Total hysterektomi", 3),
]

# (ATC-kod, substans, beredningsform, styrkor, vikt)
DRUGS = [
    ("N02BE01", "Paracetamol", "Tablett", ["500 mg", "665 mg", "1 g"], 30), ("M01AE01", "Ibuprofen", "Tablett", ["200 mg", "400 mg", "600 mg"], 14),
    ("C07AB02", "Metoprolol", "Depottablett", ["25 mg", "50 mg", "100 mg"], 16), ("C09AA02", "Enalapril", "Tablett", ["5 mg", "10 mg", "20 mg"], 12),
    ("C09CA01", "Losartan", "Tablett", ["50 mg", "100 mg"], 11), ("C08CA01", "Amlodipin", "Tablett", ["5 mg", "10 mg"], 13),
    ("C10AA05", "Atorvastatin", "Tablett", ["10 mg", "20 mg", "40 mg", "80 mg"], 17), ("C10AA01", "Simvastatin", "Tablett", ["20 mg", "40 mg"], 9),
    ("A10BA02", "Metformin", "Tablett", ["500 mg", "850 mg", "1 g"], 13), ("A10AB01", "Insulin (humant)", "Injektionsvätska", ["100 E/ml"], 4),
    ("A02BC01", "Omeprazol", "Enterokapsel", ["10 mg", "20 mg", "40 mg"], 16), ("B01AC06", "Acetylsalicylsyra", "Tablett", ["75 mg", "160 mg"], 12),
    ("B01AF02", "Apixaban", "Tablett", ["2,5 mg", "5 mg"], 9), ("B01AA03", "Warfarin", "Tablett", ["2,5 mg"], 4),
    ("H03AA01", "Levotyroxin", "Tablett", ["25 mikrogram", "50 mikrogram", "100 mikrogram"], 11), ("N06AB06", "Sertralin", "Tablett", ["25 mg", "50 mg", "100 mg"], 10),
    ("N06AB04", "Citalopram", "Tablett", ["10 mg", "20 mg"], 6), ("R03AC02", "Salbutamol", "Inhalationspulver", ["0,2 mg/dos"], 7),
    ("J01CE02", "Fenoximetylpenicillin", "Tablett", ["800 mg", "1 g"], 9), ("J01CA04", "Amoxicillin", "Tablett", ["500 mg", "750 mg"], 6),
    ("C03CA01", "Furosemid", "Tablett", ["20 mg", "40 mg"], 8), ("N05CF01", "Zopiklon", "Tablett", ["5 mg", "7,5 mg"], 7),
    ("N02AA05", "Oxikodon", "Depottablett", ["5 mg", "10 mg", "20 mg"], 4), ("H02AB06", "Prednisolon", "Tablett", ["2,5 mg", "5 mg", "10 mg"], 5),
]

# (analys, enhet, referens lägsta, referens högsta, decimaler, vikt)
LABS = [
    ("B-Hemoglobin", "g/L", 117, 170, 0, 20), ("P-Glukos", "mmol/L", 4.0, 6.0, 1, 16), ("B-HbA1c", "mmol/mol", 27, 42, 0, 10),
    ("P-Kreatinin", "µmol/L", 45, 105, 0, 16), ("P-CRP", "mg/L", 0, 5, 0, 18), ("P-Natrium", "mmol/L", 137, 145, 0, 12),
    ("P-Kalium", "mmol/L", 3.5, 4.4, 1, 12), ("B-Leukocyter", "10^9/L", 3.5, 8.8, 1, 14), ("B-Trombocyter", "10^9/L", 145, 387, 0, 10),
    ("P-ALAT", "µkat/L", 0.15, 1.1, 2, 8), ("P-TSH", "mIE/L", 0.4, 4.0, 2, 7), ("P-Kolesterol", "mmol/L", 3.9, 7.8, 1, 6),
    ("P-LDL-kolesterol", "mmol/L", 2.0, 5.3, 1, 5), ("P-PSA", "µg/L", 0, 3, 1, 3), ("P-Troponin T", "ng/L", 0, 14, 0, 4),
    ("P-Albumin", "g/L", 36, 48, 0, 5),
]

CLINICS = ["Medicinkliniken", "Kirurgkliniken", "Ortopedkliniken", "Kardiologkliniken", "Akutkliniken", "Kvinnokliniken",
           "Barn- och ungdomskliniken", "Psykiatriska kliniken", "Ögonkliniken", "Öron-, näs- och halskliniken",
           "Infektionskliniken", "Onkologkliniken", "Hudkliniken", "Urologkliniken", "Neurologkliniken", "Röntgenkliniken"]
HOME_HSA_ORG = "2321000214"  # organisationsdelen i hemregionens HSA-id (kontrollera mot er HSA-katalog)
HOSPITAL_TYPES = ["Centralsjukhuset", "Länssjukhuset", "Universitetssjukhuset", "Närsjukhuset", "Lasarettet"]

CARE_NOTES = [
    "Patienten mår efter omständigheterna väl.", "Återbesök planeras om fyra veckor.", "Remiss skickad till specialistmottagning.",
    "Patienten informerad om provsvar per telefon.", "Läkemedelslistan genomgången tillsammans med patienten.",
    "Ingen känd överkänslighet.", "Uppföljning via telefon om en vecka.", "Patienten uteblev från bokat besök.",
    "Blodtryck kontrollerat utan anmärkning.", "Anhörig närvarande vid besöket.", "Sjukskrivning förlängd två veckor.",
    "Kontakt tagen med kommunens hemsjukvård.", "Egenvårdsråd givna.", "Provtagning ordinerad inför nästa besök.",
    "Vårdplan upprättad i samråd med patienten.", "Tolk närvarande vid besöket.", "Patienten önskar byta tid.",
    "Inskriven för observation över natten.", "Utskrivningsklar, väntar på transport.", "Receptförnyelse utförd.",
]

CARE_PRESETS = {
    "care_ward": ["Avdelning 108 | 12", "Avdelning 109 | 12", "Avdelning 110 | 10", "Avdelning 204 | 10", "Avdelning 212 | 10",
                  "Akutvårdsavdelningen (AVA) | 16", "Intensivvårdsavdelningen (IVA) | 6", "Hjärtintensiven (HIA) | 8", "Barnavdelningen | 8", "BB-avdelningen | 8"],
    "care_contact_type": ["Besök | 70", "Vårdtillfälle | 12", "Distanskontakt | 14", "Hembesök | 4"],
    "care_form": ["Primärvård | 55", "Specialiserad öppenvård | 30", "Slutenvård | 10", "Hemsjukvård | 5"],
    "care_profession": ["Läkare | 40", "Sjuksköterska | 28", "Undersköterska | 8", "Fysioterapeut | 8", "Psykolog | 4",
                        "Kurator | 3", "Arbetsterapeut | 3", "Barnmorska | 3", "Dietist | 1", "Biomedicinsk analytiker | 2"],
    "care_visit_type": ["Återbesök | 50", "Nybesök | 30", "Akutbesök | 20"],
    "care_triage": ["Grön | 40", "Gul | 32", "Orange | 15", "Blå | 8", "Röd | 5"],
    "care_referral_status": ["Besvarad | 45", "Accepterad | 20", "Bedömd | 12", "Mottagen | 10", "Skickad | 8", "Avvisad | 5"],
    "care_admission": ["Akut | 65", "Planerad | 35"],
    "care_discharge": ["Hemmet | 82", "Särskilt boende | 8", "Annan vårdenhet | 7", "Avliden | 3"],
    "care_booking_status": ["Genomförd | 70", "Bokad | 12", "Avbokad | 8", "Uteblev | 6", "Ankommen | 4"],
    "care_fee": ["0 | 15", "100 | 15", "200 | 35", "300 | 25", "400 | 10"],
    "care_diagnosis_type": ["Huvuddiagnos | 60", "Bidiagnos | 40"],
}


# --- samband: vilka diagnoser som passar ålder/kön, och vilka läkemedel och analyser som hör till en diagnos
# kod -> (lägsta ålder, högsta ålder, kön "M"/"K"/None)
DIAG_RULES = {
    "I10.9": (35, 120, None), "E11.9": (40, 120, None), "E10.9": (5, 60, None), "I48.9": (55, 120, None), "J44.9": (50, 120, None),
    "I50.9": (60, 120, None), "E78.0": (40, 120, None), "M17.9": (50, 120, None), "M16.9": (55, 120, None), "I25.9": (55, 120, None),
    "I21.9": (45, 120, None), "I63.9": (55, 120, None), "S72.0": (65, 120, None), "C50.9": (35, 120, "K"), "C61.9": (50, 120, "M"),
    "C34.9": (50, 120, None), "H25.9": (60, 120, None), "H66.9": (0, 14, None), "F32.9": (15, 120, None), "F41.9": (15, 120, None),
    "F43.9": (18, 70, None), "M54.5": (18, 120, None), "K80.2": (25, 120, None), "N20.0": (20, 120, None), "E03.9": (25, 120, None),
    "G43.9": (12, 65, None), "K21.9": (20, 120, None),
}
DIAG_DRUGS = {
    "I10.9": ["C09AA02", "C09CA01", "C08CA01", "C07AB02"], "E11.9": ["A10BA02", "C10AA05"], "E10.9": ["A10AB01"],
    "J06.9": ["N02BE01", "J01CE02"], "M54.5": ["N02BE01", "M01AE01"], "N39.0": ["J01CA04"], "F32.9": ["N06AB06", "N06AB04"],
    "F41.9": ["N06AB06"], "I48.9": ["B01AF02", "B01AA03", "C07AB02"], "J45.9": ["R03AC02"], "J44.9": ["R03AC02", "H02AB06"],
    "I50.9": ["C03CA01", "C07AB02", "C09AA02"], "J18.9": ["J01CE02", "J01CA04"], "E78.0": ["C10AA05", "C10AA01"],
    "E03.9": ["H03AA01"], "M17.9": ["N02BE01", "M01AE01"], "M16.9": ["N02BE01", "M01AE01"], "I25.9": ["B01AC06", "C10AA05", "C07AB02"],
    "I21.9": ["B01AC06", "C10AA05", "C07AB02"], "I63.9": ["B01AC06", "C10AA05"], "K21.9": ["A02BC01"], "S72.0": ["N02BE01", "N02AA05"],
    "S52.5": ["N02BE01"], "H66.9": ["J01CE02"], "G43.9": ["N02BE01", "M01AE01"], "F43.9": ["N05CF01"],
    "C50.9": ["N02BE01", "N02AA05"], "C61.9": ["N02BE01", "N02AA05"], "C34.9": ["N02AA05"], "R51.9": ["N02BE01"],
}
# diagnos -> [(analys, förväntad avvikelse "H"/"L"/None)]
DIAG_LABS = {
    "E11.9": [("B-HbA1c", "H"), ("P-Glukos", "H")], "E10.9": [("B-HbA1c", "H"), ("P-Glukos", "H")],
    "I10.9": [("P-Kreatinin", None), ("P-Kalium", None)], "D50.9": [("B-Hemoglobin", "L")],
    "J18.9": [("P-CRP", "H"), ("B-Leukocyter", "H")], "N39.0": [("P-CRP", "H")], "I21.9": [("P-Troponin T", "H")],
    "R07.4": [("P-Troponin T", None)], "E78.0": [("P-Kolesterol", "H"), ("P-LDL-kolesterol", "H")], "E03.9": [("P-TSH", "H")],
    "C61.9": [("P-PSA", "H")], "I50.9": [("P-Kreatinin", "H"), ("P-Natrium", "L")], "A09.9": [("P-CRP", "H"), ("P-Kalium", "L")],
    "B34.9": [("P-CRP", None)],
}
# --- kroniska sjukdomar på patientnivå (steg C mot en förloppsmodell)
# Förekomsten är grova uppskattningar för svensk vuxenbefolkning, inte officiell statistik – kalibrera gärna med
# "Lär från produktion". prev: [(lägsta ålder, högsta ålder, procent)], sex: faktor per kön, need: hur mycket vård
# sjukdomen ger upphov till, labs: analyser som följs och åt vilket håll sjukdomen drar dem.
CHRONIC = {
    "I10.9": {"prev": [(18, 44, 3), (45, 64, 20), (65, 79, 45), (80, 120, 55)], "need": 0.8, "labs": [("P-Kreatinin", None), ("P-Kalium", None)]},
    "E11.9": {"prev": [(18, 44, 1), (45, 64, 6), (65, 79, 14), (80, 120, 15)], "sex": {"M": 1.3, "K": 0.8}, "need": 1.5,
              "labs": [("B-HbA1c", "H"), ("P-Glukos", "H"), ("P-Kreatinin", None)]},
    "E10.9": {"prev": [(5, 70, 0.5)], "need": 2.0, "labs": [("B-HbA1c", "H"), ("P-Glukos", "H")]},
    "J45.9": {"prev": [(3, 17, 8), (18, 120, 6)], "need": 0.6, "labs": []},
    "J44.9": {"prev": [(45, 64, 3), (65, 120, 8)], "need": 1.4, "labs": [("P-CRP", None)]},
    "I48.9": {"prev": [(50, 64, 2), (65, 79, 8), (80, 120, 15)], "sex": {"M": 1.2, "K": 0.85}, "need": 1.2,
              "labs": [("B-Hemoglobin", None), ("P-Kreatinin", None)]},
    "I50.9": {"prev": [(55, 64, 1), (65, 79, 4), (80, 120, 12)], "need": 2.2, "labs": [("P-Kreatinin", "H"), ("P-Natrium", "L"), ("P-Kalium", None)]},
    "E78.0": {"prev": [(40, 120, 10)], "need": 0.4, "labs": [("P-LDL-kolesterol", "H"), ("P-Kolesterol", "H")]},
    "E03.9": {"prev": [(20, 120, 3)], "sex": {"K": 1.6, "M": 0.3}, "need": 0.4, "labs": [("P-TSH", "H")]},
    "F32.9": {"prev": [(15, 64, 6), (65, 120, 4)], "sex": {"K": 1.3, "M": 0.7}, "need": 1.0, "labs": []},
    "F41.9": {"prev": [(15, 64, 6), (65, 120, 3)], "sex": {"K": 1.3, "M": 0.7}, "need": 0.8, "labs": []},
    "M17.9": {"prev": [(50, 64, 5), (65, 120, 12)], "need": 0.6, "labs": []},
    "I25.9": {"prev": [(55, 64, 2), (65, 79, 7), (80, 120, 12)], "sex": {"M": 1.4, "K": 0.6}, "need": 1.0,
              "labs": [("P-LDL-kolesterol", "H"), ("P-Kreatinin", None)]},
    "D50.9": {"prev": [(15, 50, 3), (51, 120, 1)], "sex": {"K": 1.8, "M": 0.3}, "need": 0.5, "labs": [("B-Hemoglobin", "L")]},
}
INPATIENT = {"I50.9", "S72.0", "J18.9", "I21.9", "I63.9", "K35.8", "C34.9", "J44.9"}  # leder oftare till inläggning
_FEMALE = {"k", "kvinna", "f", "female", "2"}
_PROFILE_CACHE: dict = {}
_CODE_CACHE: dict = {}


def _book(project, kind: str):
    """Projektets eget kodverk (äldre projekt), annars domänbibliotekets."""
    own = (project.codebooks or {}).get(kind) if project is not None else None
    if own:
        return own
    from . import library
    return library.codebook(kind)


def _norm_code(code) -> str:
    return str(code).replace(".", "").replace(" ", "").upper()


def _codes(ctx, kind: str, builtin: list) -> tuple[list, list]:
    """(koder, kumulativa vikter). Ett inläst kodverk läggs till de inbyggda exemplen; vanliga koder förblir vanliga."""
    book = _book(ctx.project, kind)
    key = (kind, id(book), len(book) if book else 0, _g.LIST_REVISION)
    hit = _CODE_CACHE.get(key)
    if hit is None:
        items = list(builtin)
        if book:
            known = {_norm_code(i[0]) for i in builtin}
            extra = [r for r in book if r and _norm_code(r[0]) not in known]
            if extra:
                w = 0.43 * sum(i[-1] for i in builtin) / len(extra)  # hela kodverket står för ca 30 % av dragningarna
                width = len(builtin[0])
                for r in extra:
                    text = str(r[1]) if len(r) > 1 else ""
                    items.append((str(r[0]).strip(), text, w) if width == 3 else (str(r[0]).strip(), text, None, [None], w))
        cum, total = [], 0.0
        for i in items:
            total += i[-1]
            cum.append(total)
        hit = _CODE_CACHE[key] = (items, cum)
        if len(_CODE_CACHE) > 12:
            _CODE_CACHE.pop(next(iter(_CODE_CACHE)))
    return hit


def codebook_size(project, kind: str, builtin: list) -> int:
    book = _book(project, kind)
    if not book:
        return len(builtin)
    known = {_norm_code(i[0]) for i in builtin}
    return len(builtin) + sum(1 for r in book if r and _norm_code(r[0]) not in known)


def _pick(ctx, kind: str, builtin: list):
    """Kodtabeller får en kod per rad i ordning; övriga tabeller ett viktat slumpval."""
    items, cum = _codes(ctx, kind, builtin)
    if ctx.table.category == "reference":
        return items[(ctx.index + ctx.offset) % len(items)]
    return ctx.rng.choices(items, cum_weights=cum, k=1)[0]


def _person_info(data, row) -> tuple[int | None, bool | None]:
    """(ålder, kvinna) från en personrad, utifrån kolumnernas generatorer."""
    age = female = None
    for c in data.table.columns:
        if c.name not in data.colidx:
            continue
        v = row[data.colidx[c.name]]
        if v is None:
            continue
        if c.generator == "person.birthdate" and hasattr(v, "year"):
            age = (date.today() - (v.date() if hasattr(v, "date") else v)).days // 365
        elif c.generator == "person.gender":
            female = str(v).strip().lower() in _FEMALE
    return age, female


def _prevalence(spec: dict, age, female) -> float:
    a = 45 if age is None else age
    pct = next((p for lo, hi, p in spec["prev"] if lo <= a <= hi), 0.0)
    sex = spec.get("sex") or {}
    if female is not None:
        pct *= sex.get("K" if female else "M", 1.0)
    return pct / 100


def patient_profile(seed, data, idx: int) -> dict:
    """Patientens kroniska sjukdomar, fasta läkemedel och egna nivåer för labbvärden.

    Räknas fram ur patientraden och slumpfröet, så att samma patient får samma profil i alla tabeller.
    """
    key = (seed, data.table.key, idx, id(data), _g.LIST_REVISION)
    hit = _PROFILE_CACHE.get(key)
    if hit is not None:
        return hit
    age, female = _person_info(data, data.rows[idx])
    rng = random.Random(f"{seed}:patient:{data.table.key}:{idx}")
    known = {d[0] for d in DIAGNOSES}
    chronic = [code for code, spec in CHRONIC.items() if code in known and rng.random() < _prevalence(spec, age, female)]
    drugs = {}
    for code in chronic:  # samma preparat och styrka för sjukdomen år efter år
        fitting = [x for x in DRUGS if x[0] in DIAG_DRUGS.get(code, [])]
        if fitting:
            d = rng.choice(fitting)
            drugs[code] = (d, rng.choice(d[3]))
    effects = {}
    for code in chronic:
        for name, direction in CHRONIC[code]["labs"]:
            if direction:
                effects[name] = direction
    labs = {}
    for name, unit, lo, hi, dec, _ in LABS:  # patientens egen nivå per analys
        if effects.get(name) == "H":
            base = hi * (rng.uniform(1.5, 4.0) if lo == 0 else rng.uniform(1.15, 1.6))
        elif effects.get(name) == "L":
            base = lo * rng.uniform(0.72, 0.93)
        elif lo == 0:
            base = hi * rng.betavariate(1.5, 4)
        else:
            base = rng.gauss((lo + hi) / 2, (hi - lo) / 7)
        labs[name] = base
    need = 1.0 + 0.015 * max(0, (age if age is not None else 45) - 40) + sum(CHRONIC[c]["need"] for c in chronic)
    prof = {"age": age, "female": female, "chronic": chronic, "drugs": drugs, "labs": labs, "effects": effects, "need": need}
    if len(_PROFILE_CACHE) > 300_000:
        _PROFILE_CACHE.clear()
    _PROFILE_CACHE[key] = prof
    return prof


def _care_need(seed, data, idx):
    """Vikt för fördelningen 'efter vårdbehov': äldre och kroniker får fler vårdkontakter."""
    if data.table.category != "person" or not any(c.generator in ("person.birthdate", "person.gender") for c in data.table.columns):
        return None
    return patient_profile(seed, data, idx)["need"]


_g.PARENT_WEIGHTS.append(_care_need)


def _episode(ctx):
    """Vårdhändelsen som raden hör till: en förälder i en transaktionstabell, annars raden själv eller en person.

    {"key": nyckel för händelsen, "info": (ålder, kvinna), "own": raden är själv händelsen, "person": (data, index) eller None}
    """
    def build():
        refs = [r for r in ctx.parents.values() if r is not None]
        ep = next((r for r in refs if r[0].table.category == "transaction"), None)
        person = next((r for r in refs if r[0].table.category == "person"), None)
        if ep is not None:
            data, idx = ep
            info, pref = (None, None), person
            for fk in data.table.foreign_keys:  # vårdhändelsens patient
                pdata = ctx.table_data(fk.ref_table)
                if pdata is not None and pdata.table.category == "person" and all(c in data.colidx for c in fk.columns):
                    pos = pdata.position(fk.ref_columns, tuple(data.rows[idx][data.colidx[c]] for c in fk.columns))
                    if pos is not None:
                        info, pref = _person_info(pdata, pdata.rows[pos]), (pdata, pos)
                        break
            if pref is not None and info == (None, None):
                info = _person_info(pref[0], pref[0].rows[pref[1]])
            return {"key": f"{data.table.key}:{idx}", "info": info, "own": False, "person": pref}
        if ctx.table.category == "transaction":
            info = _person_info(person[0], person[0].rows[person[1]]) if person else (None, None)
            return {"key": f"{ctx.table.key}:{ctx.index}", "info": info, "own": True, "person": person}
        if person is not None:
            return {"key": f"{person[0].table.key}:{person[1]}", "info": _person_info(person[0], person[0].rows[person[1]]),
                    "own": False, "person": person}
        return None
    return ctx.entity("care:episode", build)


def _profile(ctx) -> dict | None:
    ep = _episode(ctx)
    return patient_profile(ctx.seed, *ep["person"]) if ep and ep["person"] else None


def _diag(code: str):
    return next((d for d in DIAGNOSES if d[0] == code), (code, code, 1))


def _acute_pool(age, female, prof):
    """Diagnoser som kan uppstå akut. Har patienten en profil räknas inte kroniska sjukdomar som hen saknar."""
    pool = [d for d in DIAGNOSES if _fits(d[0], age, female) and (prof is None or d[0] not in CHRONIC)]
    return pool or DIAGNOSES


def latent_diagnosis(ctx):
    """En dold 'orsak' per vårdhändelse som diagnos, läkemedel och provsvar i olika tabeller kan dela.

    Har patienten kroniska sjukdomar handlar de flesta kontakter om dem; annars, och ibland ändå, ett akut tillstånd
    som passar patientens ålder och kön. Valet är deterministiskt per vårdhändelse.
    """
    ep = _episode(ctx)
    if ep is None:
        return None, False

    def build():
        age, female = ep["info"]
        prof = patient_profile(ctx.seed, *ep["person"]) if ep["person"] else None
        rnd = random.Random(f"{ctx.seed}:{ep['key']}")
        if prof and prof["chronic"] and rnd.random() < min(0.8, 0.35 + 0.12 * len(prof["chronic"])):
            code = rnd.choices(prof["chronic"], weights=[CHRONIC[c]["need"] for c in prof["chronic"]], k=1)[0]
            return _diag(code)
        pool = _acute_pool(age, female, prof)
        return rnd.choices(pool, weights=[d[-1] for d in pool], k=1)[0]
    return ctx.entity("care:latent", build), ep["own"]


def _first_in_episode(ctx) -> bool:
    seqs = [ctx.parent_seq(c) for c, r in ctx.parents.items() if r is not None and r[0].table.category == "transaction"]
    return not seqs or seqs[0] == 0


def _fits(code: str, age, female) -> bool:
    lo, hi, sex = DIAG_RULES.get(code, (0, 120, None))
    if age is not None and not lo <= age <= hi:
        return False
    return not (female is not None and sex is not None and (sex == "K") != female)


def diagnosis(ctx, group=""):
    def build():
        if ctx.table.category == "reference":
            return _pick(ctx, "diagnosis", DIAGNOSES)
        lat, own = latent_diagnosis(ctx)
        ep = _episode(ctx)
        prof = _profile(ctx)
        if lat is not None:
            # första diagnosen för en vårdkontakt är dess huvudorsak; följande är oftast patientens andra sjukdomar (bidiagnoser)
            first = own or _first_in_episode(ctx)
            if first and ctx.rng.random() < 0.9:
                return lat
            others = [c for c in (prof or {}).get("chronic", []) if c != lat[0]]
            if not first and others and ctx.rng.random() < 0.7:
                return _diag(ctx.rng.choice(others))
            if not first and ctx.rng.random() < 0.15:
                return lat
        age, female = ep["info"] if ep else (None, None)
        if prof is not None:  # bara akuta tillstånd – kroniska sjukdomar som patienten saknar uppstår inte
            pool = _acute_pool(age, female, prof)
            return _weighted(ctx.rng, pool, [d[-1] for d in pool])
        for _ in range(12):  # även slumpade diagnoser ska passa patientens ålder och kön
            d = _pick(ctx, "diagnosis", DIAGNOSES)
            if _fits(d[0], age, female):
                return d
        return d
    return ctx.entity("diagnosis:" + (group or ""), build)


def procedure(ctx, group=""):
    return ctx.entity("procedure:" + (group or ""), lambda: _pick(ctx, "procedure", PROCEDURES))


def drug(ctx, group=""):
    def build():
        d = strength = None
        if ctx.table.category != "reference":
            lat, _ = latent_diagnosis(ctx)
            prof = _profile(ctx)
            fixed = (prof or {}).get("drugs") or {}
            first = _first_in_episode(ctx)
            if lat is not None and lat[0] in fixed and first and ctx.rng.random() < 0.85:
                d, strength = fixed[lat[0]]  # kontaktens kroniska sjukdom: patientens vanliga preparat
            elif fixed and (not first or lat is None or lat[0] not in DIAG_DRUGS) and ctx.rng.random() < 0.7:
                d, strength = fixed[ctx.rng.choice(sorted(fixed))]  # övriga ordinationer: patientens andra stående läkemedel
            else:
                wanted = DIAG_DRUGS.get(lat[0]) if lat is not None else None
                fitting = [x for x in DRUGS if x[0] in wanted] if wanted else []
                if fitting and ctx.rng.random() < 0.75:
                    d = ctx.rng.choice(fitting)
        d = d or _pick(ctx, "drug", DRUGS)
        return {"atc": d[0], "name": d[1], "form": d[2], "strength": strength or ctx.rng.choice(d[3])}
    return ctx.entity("drug:" + (group or ""), build)


def _row_date(ctx):
    """Radens huvuddatum (t.ex. provtagningsdatum), om tabellen har ett – för att låta värden förändras över tid."""
    name = ctx.shared.get("care_date_col", "?")
    if name == "?":
        name = next((c.name for c in ctx.table.columns if c.kind in ("date", "datetime") and c.generator.startswith("date.")
                     and c.generator != "date.part"), None)
        ctx.shared["care_date_col"] = name
    if not name or ctx.column is not None and ctx.column.name == name:
        return None
    try:
        d = ctx.get(name)
    except ValueError:
        return None
    return d.date() if isinstance(d, datetime) else d if isinstance(d, date) else None


def lab(ctx, group=""):
    def build():
        rng = ctx.rng
        pick, bias = None, None
        prof = None
        if ctx.table.category != "reference":
            lat, _ = latent_diagnosis(ctx)
            prof = _profile(ctx)
            wanted = DIAG_LABS.get(lat[0]) if lat is not None else None
            monitored = sorted({n for c in (prof or {}).get("chronic", []) for n, _ in CHRONIC[c]["labs"]})
            if wanted and rng.random() < 0.5:
                name, bias = rng.choice(wanted)
                pick = next((x for x in LABS if x[0] == name), None)
            elif monitored and rng.random() < 0.6:  # kronikerns kontrollprover
                pick = next((x for x in LABS if x[0] == rng.choice(monitored)), None)
        if pick is None:
            pick = LABS[(ctx.index + ctx.offset) % len(LABS)] if ctx.table.category == "reference" else _weighted(rng, LABS, [x[-1] for x in LABS])
        name, unit, lo, hi, dec, _ = pick
        if prof is not None and name in prof["labs"] and not (bias and rng.random() < 0.6):
            # patientens egen nivå; avvikande värden hos kroniker närmar sig det normala med tiden (behandlingen verkar)
            base, mid = prof["labs"][name], (lo + hi) / 2 if lo > 0 else hi / 2
            if name in prof["effects"]:
                d = _row_date(ctx)
                years_ago = max(0.0, (ctx.today - d).days / 365.25) if d else 1.5
                base = mid + (base - mid) * (0.55 + 0.45 * min(1.0, years_ago / 3))
            spread = (hi - lo) / 14 if lo > 0 else max(base * 0.18, hi / 20)
            value = max(lo * 0.4 if lo > 0 else 0.0, rng.gauss(base, spread))
            value = int(round(value)) if dec == 0 else round(value, dec)
            return {"name": name, "unit": unit, "low": lo, "high": hi, "value": value,
                    "flag": "H" if value > hi else "L" if value < lo else None}
        if bias == "H" and rng.random() < 0.6:
            value = hi * rng.uniform(1.05, 1.9)
        elif bias == "L" and rng.random() < 0.6:
            value = lo * rng.uniform(0.6, 0.97)
        elif lo == 0:  # analyser där låga värden är normala: de flesta inom intervallet, några klart förhöjda
            value = hi * rng.betavariate(1.2, 3) if rng.random() < 0.8 else hi * rng.uniform(1.1, 8)
        else:
            value = max(lo * 0.5, rng.gauss((lo + hi) / 2, (hi - lo) / 3.2))
        value = int(round(value)) if dec == 0 else round(value, dec)
        return {"name": name, "unit": unit, "low": lo, "high": hi, "value": value,
                "flag": "H" if value > hi else "L" if value < lo else None}
    return ctx.entity("lab:" + (group or ""), build)


def care_unit(ctx, group=""):
    def build():
        rng = ctx.rng
        a = address(ctx, group)
        lan = a["county"]
        home = lan == vocab.HOME_COUNTY
        region = vocab.HOME_REGION if home else "Västra Götalandsregionen" if lan.startswith("Västra Götaland") else "Region " + lan.removesuffix(" län").removesuffix("s")
        suffix = "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        # hemregionens enheter delar organisationsdel i HSA-id; övriga regioner får en påhittad
        hsa = f"SE{HOME_HSA_ORG if home else rng.randint(2120000000, 2329999999)}-{suffix}"
        if rng.random() < 0.45:
            place = rng.choice(vocab.OSTERSUND_UNITS) if a["city"] == "Östersund" else a["city"]
            return {"unit": f"{'Hälsocentralen' if home else 'Vårdcentralen'} {place}", "clinic": "Hälsocentral" if home else "Vårdcentral",
                    "hospital": None, "form": "Primärvård", "region": region, "hsa": hsa, "city": a["city"]}
        clinic = rng.choice(CLINICS)
        hospital = "Östersunds sjukhus" if home else f"{rng.choice(HOSPITAL_TYPES)} {a['city']}"
        inpatient = rng.random() < 0.3
        unit = f"Avdelning {rng.randint(1, 40)}" if inpatient else clinic.replace("kliniken", "mottagningen")
        return {"unit": f"{unit}, {hospital}", "clinic": clinic, "hospital": hospital,
                "form": "Slutenvård" if inpatient else "Specialiserad öppenvård", "region": region, "hsa": hsa, "city": a["city"]}
    return ctx.entity("careunit:" + (group or ""), build)


_HELP = "Exempelkoder i rätt format; läs in hela kodverket under Domänbibliotek → Regionens listor och kodverk om du behöver fler. Kod och text hör ihop på raden, och diagnos, läkemedel och provsvar som hör till samma vårdkontakt och patient passar ihop. I kodtabeller delas koderna ut i ordning."
ICD_FORMATS = ["I10.9 (med punkt)", "I109 (utan punkt)"]


@register("care.diagnosis_code", "Diagnoskod (ICD-10-SE)", "Vård", [Param("format", "Format", "select", ICD_FORMATS[0], ICD_FORMATS), GROUP], help=_HELP)
def gen_diag_code(ctx, p):
    code = str(diagnosis(ctx, p["group"])[0])
    if "utan" in str(p["format"]):
        return code.replace(".", "")
    return code if "." in code or len(code) <= 3 else f"{code[:3]}.{code[3:]}"


@register("care.diagnosis_text", "Diagnostext", "Vård", [GROUP], help=_HELP)
def gen_diag_text(ctx, p):
    return diagnosis(ctx, p["group"])[1]


CONTACT_TYPES = ["Besök", "Vårdtillfälle", "Distanskontakt", "Hembesök"]
VISIT_TYPES = ["Återbesök", "Nybesök", "Akutbesök"]


def _person_seq(ctx):
    """Hur många kontakter patienten redan har fått (0 = den första)."""
    for c, r in ctx.parents.items():
        if r is not None and r[0].table.category == "person":
            return ctx.parent_seq(c)
    return None


@register("care.contact_type", "Kontakttyp (efter orsak)", "Vård", [],
          help="Besök, vårdtillfälle, distanskontakt eller hembesök utifrån kontaktens orsak: hjärtsvikt, höftfraktur och "
               "lunginflammation leder oftare till inläggning, kroniker följs ofta upp på distans och de äldsta får hembesök.")
def gen_contact_type(ctx, p):
    lat, _ = latent_diagnosis(ctx)
    prof = _profile(ctx) or {}
    code = lat[0] if lat else ""
    if code in INPATIENT:
        w = [40, 55, 3, 2]
    elif code in prof.get("chronic", []):
        w = [62, 4, 26, 8 if (prof.get("age") or 0) >= 80 else 2]
    else:
        w = [74, 6, 18, 2]
    return _weighted(ctx.rng, CONTACT_TYPES, w)


@register("care.visit_type", "Besökstyp (efter patientens historik)", "Vård", [],
          help="Patientens första kontakt är ett nybesök; uppföljning av kroniska sjukdomar är oftast återbesök och akuta tillstånd ofta akutbesök.")
def gen_visit_type(ctx, p):
    if _person_seq(ctx) == 0:
        return "Nybesök"
    lat, _ = latent_diagnosis(ctx)
    prof = _profile(ctx) or {}
    code = lat[0] if lat else ""
    if code in prof.get("chronic", []):
        w = [80, 12, 8]
    elif code in INPATIENT:
        w = [10, 20, 70]
    else:
        w = [15, 45, 40]
    return _weighted(ctx.rng, VISIT_TYPES, w)


@register("care.procedure_code", "Åtgärdskod (KVÅ)", "Vård", [GROUP], help=_HELP)
def gen_proc_code(ctx, p):
    return procedure(ctx, p["group"])[0]


@register("care.procedure_text", "Åtgärdstext", "Vård", [GROUP], help=_HELP)
def gen_proc_text(ctx, p):
    return procedure(ctx, p["group"])[1]


def _simple(key, label, entity, field, help=_HELP):
    @register(f"care.{key}", label, "Vård", [GROUP], help=help)
    def gen(ctx, p):
        return entity(ctx, p["group"])[field]
    return gen


_simple("atc_code", "Läkemedel: ATC-kod", drug, "atc")
_simple("drug_name", "Läkemedel: substans", drug, "name")
_simple("drug_form", "Läkemedel: beredningsform", drug, "form")
_simple("drug_strength", "Läkemedel: styrka", drug, "strength")
_LAB = "Analys, värde, enhet och referensintervall hör ihop på raden. Ungefär var femte värde hamnar utanför referensintervallet."
_simple("lab_name", "Labb: analysnamn", lab, "name", _LAB)
_simple("lab_value", "Labb: resultatvärde", lab, "value", _LAB)
_simple("lab_unit", "Labb: enhet", lab, "unit", _LAB)
_simple("lab_ref_low", "Labb: referens lägsta", lab, "low", _LAB)
_simple("lab_ref_high", "Labb: referens högsta", lab, "high", _LAB)
_simple("lab_flag", "Labb: avvikelseflagga (H/L)", lab, "flag", _LAB)
_UNIT = "Vårdenhet, klinik, sjukhus, region och HSA-id hör ihop på raden."
_simple("unit_name", "Vårdenhet: namn", care_unit, "unit", _UNIT)
_simple("clinic", "Vårdenhet: klinik", care_unit, "clinic", _UNIT)
_simple("hospital", "Vårdenhet: sjukhus", care_unit, "hospital", _UNIT)
_simple("care_form", "Vårdenhet: vårdform", care_unit, "form", _UNIT)
_simple("region", "Vårdenhet: region", care_unit, "region", _UNIT)
_simple("hsa_id", "HSA-id", care_unit, "hsa", "Påhittat HSA-id i rätt format (SE + organisationsnummer + löpdel).")


@register("care.lab_ref_interval", "Labb: referensintervall (text)", "Vård", [GROUP], help=_LAB)
def gen_lab_ref(ctx, p):
    e = lab(ctx, p["group"])
    return f"{e['low']}–{e['high']}".replace(".", ",")


vocab.PRESETS.update(CARE_PRESETS)
_g._build_labels()  # etiketterna ska finnas oavsett vilken modul som importeras först
