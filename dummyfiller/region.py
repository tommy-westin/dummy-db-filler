"""Regionens övriga domäner: ekonomi (budget, leverantörsfakturor), personal och tandvård.

Kontoplan, ansvar, befattningar, löner och tandvårdsåtgärder är exempel i rimligt format – inte regionens
riktiga kodplan och inte gällande prislistor. Behöver ni de riktiga koderna: läs in dem som värdelistor under
steg 5, gärna som CSV med kod och benämning så att de hålls ihop radvis.

I tabeller med kategorin 'Referens / kodtabell' delas koderna ut i ordning (en per rad),
annars slumpas de så att vanliga koder förekommer oftare.
"""
from __future__ import annotations

from . import generators as _g
from . import vocab
from .generators import GROUP, Param, _weighted, luhn_digit, parse_date_spec, register

# ---------------------------------------------------------------- ekonomi

# (konto, benämning, lägsta belopp, högsta belopp per bokning, vikt)
ACCOUNTS = [
    ("3011", "Patientavgifter öppen vård", 100, 400, 14), ("3012", "Patientavgifter sluten vård", 130, 1500, 4),
    ("3051", "Tandvårdsavgifter", 300, 6000, 6), ("3511", "Riktade statsbidrag", 50000, 2500000, 2),
    ("3611", "Försäljning av hälso- och sjukvård", 2000, 250000, 3), ("4511", "Köp av hälso- och sjukvård", 5000, 600000, 6),
    ("4521", "Köp av riks- och regionvård", 15000, 900000, 4), ("5011", "Månadslön", 20000, 900000, 16),
    ("5021", "Timlön", 2000, 120000, 6), ("5111", "Semesterlön", 2000, 150000, 4), ("5121", "Sjuklön", 1000, 60000, 4),
    ("5611", "Arbetsgivaravgifter", 6000, 300000, 10), ("5711", "Pensionskostnader", 3000, 200000, 6),
    ("6011", "Lokalhyror", 10000, 450000, 5), ("6211", "El och uppvärmning", 2000, 120000, 3),
    ("6411", "Förbrukningsinventarier", 300, 45000, 7), ("6451", "Sjukvårdsmaterial", 200, 180000, 12),
    ("6461", "Läkemedel", 500, 400000, 10), ("6471", "Laboratoriematerial", 300, 90000, 4),
    ("6511", "Kontorsmaterial", 100, 8000, 5), ("6811", "Telefoni och datakommunikation", 300, 40000, 4),
    ("6841", "IT-tjänster och licenser", 1000, 350000, 5), ("7011", "Resekostnader", 200, 15000, 5),
    ("7051", "Sjukresor", 150, 9000, 5), ("7411", "Konsulttjänster", 5000, 300000, 4),
    ("7511", "Inhyrd personal läkare", 20000, 450000, 5), ("7512", "Inhyrd personal sjuksköterskor", 15000, 300000, 5),
    ("7611", "Utbildning och kurser", 500, 40000, 4), ("7911", "Avskrivningar inventarier", 1000, 200000, 2),
]
ACCOUNT_CLASSES = {"3": "Intäkter", "4": "Köp av verksamhet", "5": "Personalkostnader", "6": "Övriga verksamhetskostnader",
                   "7": "Övriga verksamhetskostnader"}

# (ansvar, benämning, förvaltning, vikt)
_HC = [f"Hälsocentralen {t}" for t in vocab.HOME_TOWNS if t != "Östersund"] + [f"Hälsocentralen {t}" for t in vocab.OSTERSUND_UNITS]
_FTV = [f"Folktandvården {t}" for t in ("Östersund", "Frösön", "Krokom", "Järpen", "Strömsund", "Svenstavik", "Bräcke", "Hammarstrand", "Sveg")]
_SPEC = ["Akutmottagningen", "Medicinkliniken", "Kirurgkliniken", "Ortopedkliniken", "Kvinnokliniken", "Barn- och ungdomskliniken",
         "Område psykiatri", "Ögonkliniken", "Öron-, näs- och halskliniken", "Infektionskliniken", "Onkologkliniken", "Hudkliniken",
         "Röntgen", "Laboratoriemedicin", "Ambulanssjukvården", "Intensivvården"]
_STAFF = ["Regiondirektörens stab", "Ekonomiavdelningen", "HR-avdelningen", "IT-avdelningen", "Kommunikationsavdelningen",
          "Upphandlingsenheten", "Fastighetsenheten", "Kost och service"]
COST_CENTERS = (
    [(f"{10100 + i * 100}", n, "Regionstaben", 3) for i, n in enumerate(_STAFF)]
    + [(f"{21100 + i * 100}", n, "Hälso- och sjukvårdsförvaltningen", 8) for i, n in enumerate(_SPEC)]
    + [(f"{31100 + i * 100}", n, "Hälso- och sjukvårdsförvaltningen", 5) for i, n in enumerate(_HC)]
    + [(f"{41100 + i * 100}", n, "Folktandvården", 3) for i, n in enumerate(_FTV)]
    + [("51100", "Regional utveckling", "Regionala utvecklingsförvaltningen", 3), ("51200", "Kollektivtrafik", "Regionala utvecklingsförvaltningen", 3),
       ("51300", "Kultur", "Regionala utvecklingsförvaltningen", 2)]
)
# (verksamhetskod, benämning, vikt)
ACTIVITIES = [
    ("100", "Primärvård", 22), ("200", "Specialiserad somatisk vård", 34), ("300", "Specialiserad psykiatrisk vård", 8),
    ("400", "Tandvård", 6), ("500", "Övrig hälso- och sjukvård", 6), ("600", "Läkemedel", 8), ("700", "Regional utveckling", 4),
    ("800", "Trafik och infrastruktur", 5), ("900", "Politisk verksamhet", 1), ("950", "Administration och service", 6),
]

# ---------------------------------------------------------------- personal

# (befattning, yrkeskategori, lägsta månadslön, högsta månadslön, vikt)
TITLES = [
    ("Sjuksköterska", "Sjuksköterskor", 34000, 45000, 22), ("Specialistsjuksköterska", "Sjuksköterskor", 39000, 50000, 8),
    ("Röntgensjuksköterska", "Sjuksköterskor", 36000, 45000, 2), ("Ambulanssjuksköterska", "Sjuksköterskor", 38000, 47000, 2),
    ("Barnmorska", "Sjuksköterskor", 40000, 50000, 2), ("Undersköterska", "Undersköterskor", 27000, 33000, 20),
    ("Överläkare", "Läkare", 85000, 110000, 5), ("Specialistläkare", "Läkare", 72000, 90000, 4), ("ST-läkare", "Läkare", 48000, 62000, 4),
    ("AT-läkare", "Läkare", 38000, 42000, 2), ("Fysioterapeut", "Rehabilitering", 33000, 41000, 4),
    ("Arbetsterapeut", "Rehabilitering", 33000, 41000, 3), ("Psykolog", "Psykologer och kuratorer", 42000, 55000, 2),
    ("Kurator", "Psykologer och kuratorer", 35000, 43000, 2), ("Biomedicinsk analytiker", "Laboratorium och medicinsk teknik", 33000, 42000, 3),
    ("Medicinsk sekreterare", "Administration", 28000, 34000, 6), ("Tandläkare", "Tandvård", 45000, 70000, 2),
    ("Tandhygienist", "Tandvård", 31000, 39000, 1.5), ("Tandsköterska", "Tandvård", 26000, 32000, 3),
    ("Enhetschef", "Ledning", 48000, 62000, 2), ("Verksamhetschef", "Ledning", 65000, 90000, 0.6),
    ("Ekonom", "Administration", 36000, 50000, 1.5), ("HR-specialist", "Administration", 37000, 50000, 1),
    ("Systemförvaltare", "Administration", 38000, 52000, 1.5), ("Administratör", "Administration", 28000, 35000, 3),
    ("Lokalvårdare", "Service", 25000, 29000, 2), ("Kock", "Service", 27000, 32000, 1),
]
EMPLOYMENT_FORMS = [("Tillsvidare", 78), ("Vikariat", 10), ("Visstid", 7), ("Timanställd", 5)]
GRADES = [(100, 68), (90, 3), (80, 13), (75, 8), (50, 8)]

# ---------------------------------------------------------------- tandvård

# (åtgärdskod, text, lägsta pris, högsta pris, antal ytor, tandgrupp "fram"/"bak"/"valfri"/None, diagnos, vikt)
DENTAL_PROCEDURES = [
    ("101", "Basundersökning och diagnostik, tandläkare", 900, 1100, 0, None, "Z01.2", 22),
    ("103", "Kompletterande eller akut undersökning, tandläkare", 400, 600, 0, None, "K04.0", 10),
    ("107", "Omfattande kompletterande undersökning, tandläkare", 1100, 1400, 0, None, "Z01.2", 3),
    ("111", "Basundersökning, tandhygienist", 700, 900, 0, None, "Z01.2", 10),
    ("112", "Basundersökning med fullständig parodontal undersökning, tandhygienist", 900, 1200, 0, None, "K05.1", 5),
    ("121", "Röntgenundersökning av enskild tand", 60, 90, 0, "valfri", "K02.1", 8),
    ("301", "Sjukdoms- eller smärtbehandling, mindre omfattande", 400, 550, 0, "valfri", "K04.0", 8),
    ("302", "Sjukdoms- eller smärtbehandling", 800, 1000, 0, "valfri", "K04.0", 4),
    ("311", "Information eller instruktion vid risk för munhälsorelaterade sjukdomar", 450, 600, 0, None, "K05.1", 6),
    ("341", "Behandling av parodontal sjukdom eller periimplantit, mindre omfattande", 500, 700, 0, None, "K05.3", 6),
    ("342", "Behandling av parodontal sjukdom eller periimplantit, större omfattning", 1000, 1300, 0, None, "K05.3", 3),
    ("401", "Tanduttagning, en tand", 1100, 1400, 0, "valfri", "K04.5", 5),
    ("402", "Tanduttagning, när separation eller friläggning krävs", 1800, 2200, 0, "bak", "K04.5", 2),
    ("501", "Rensning och rotfyllning, en rotkanal", 3500, 4200, 0, "fram", "K04.0", 2),
    ("502", "Rensning och rotfyllning, två rotkanaler", 4300, 5000, 0, "bak", "K04.0", 1.5),
    ("503", "Rensning och rotfyllning, tre rotkanaler", 5400, 6200, 0, "bak", "K04.5", 1.5),
    ("701", "Fyllning av en yta på framtand eller hörntand", 650, 800, 1, "fram", "K02.1", 4),
    ("702", "Fyllning av två ytor på framtand eller hörntand", 1000, 1250, 2, "fram", "K02.1", 3),
    ("703", "Fyllning av tre eller flera ytor på framtand eller hörntand", 1250, 1500, 3, "fram", "K02.1", 2),
    ("704", "Fyllning av en yta på molar eller premolar", 850, 1050, 1, "bak", "K02.1", 7),
    ("705", "Fyllning av två ytor på molar eller premolar", 1250, 1500, 2, "bak", "K02.1", 6),
    ("706", "Fyllning av tre eller flera ytor på molar eller premolar", 1650, 1950, 3, "bak", "K02.1", 4),
    ("800", "Permanent tandstödd krona, en per käke", 6000, 7500, 0, "valfri", "K02.1", 2),
]
DENTAL_DIAGNOSES = [
    ("K02.1", "Dentinkaries"), ("K04.0", "Pulpit"), ("K04.5", "Kronisk apikal parodontit"), ("K05.1", "Kronisk gingivit"),
    ("K05.3", "Kronisk parodontit"), ("Z01.2", "Tandundersökning"),
]
_DIAG_TEXT = dict(DENTAL_DIAGNOSES)

REGION_PRESETS = {
    "invoice_status": ["Betald | 70", "Attesterad | 10", "Under attest | 8", "Registrerad | 6", "Bestridd | 3", "Makulerad | 3"],
    "payment_terms": ["30 dagar netto | 80", "60 dagar netto | 8", "20 dagar netto | 8", "10 dagar netto | 4"],
    "budget_version": ["Ursprunglig budget | 60", "Reviderad budget | 25", "Prognos | 15"],
    "supplier_type": ["Företag | 78", "Region eller kommun | 10", "Statlig myndighet | 7", "Enskild firma | 5"],
    "hr_absence": ["Semester | 45", "Sjukdom | 25", "Föräldraledighet | 12", "Vård av barn | 8", "Tjänstledighet | 5", "Kompensationsledighet | 5"],
    "hr_pay_type": ["Månadslön | 55", "Ob-tillägg | 14", "Övertid | 8", "Jour och beredskap | 7", "Semesterersättning | 6",
                    "Sjuklön | 5", "Timlön | 5"],
    "hr_employment_form": [f"{v} | {w}" for v, w in EMPLOYMENT_FORMS],
    "hr_administration": ["Hälso- och sjukvårdsförvaltningen | 78", "Folktandvården | 8", "Regionstaben | 9", "Regionala utvecklingsförvaltningen | 5"],
    "dental_patient_type": ["Vuxen | 62", "Barn och unga | 30", "Nödvändig tandvård | 5", "Akut | 3"],
}


def _pick(ctx, items):
    """Kodtabeller får en kod per rad i ordning; övriga tabeller ett viktat slumpval."""
    if ctx.table.category == "reference":
        return items[(ctx.index + ctx.offset) % len(items)]
    return _weighted(ctx.rng, items, [i[-1] for i in items])


ACCOUNT_SCOPES = ["Alla konton", "Endast kostnader (kontoklass 4–7)", "Endast intäkter (kontoklass 3)"]


def account(ctx, group=""):
    def build():
        scope = str(_g._table_param(ctx, "finance.account_code", group or "", "scope", ACCOUNT_SCOPES[0]))
        if ctx.table.category == "reference" or scope == ACCOUNT_SCOPES[0]:
            return _pick(ctx, ACCOUNTS)
        items = [a for a in ACCOUNTS if (a[0][0] == "3") == scope.startswith("Endast intäkter")]
        return _weighted(ctx.rng, items, [a[-1] for a in items])
    return ctx.entity("account:" + (group or ""), build)


def cost_center(ctx, group=""):
    def build():
        if ctx.table.category == "location":  # i en enhetstabell: en enhet per rad
            return COST_CENTERS[(ctx.index + ctx.offset) % len(COST_CENTERS)]
        return _pick(ctx, COST_CENTERS)
    return ctx.entity("costcenter:" + (group or ""), build)


def activity(ctx, group=""):
    def build():
        # verksamheten följer oftast ansvaret på raden: en hälsocentral bokför på primärvård, en tandvårdsklinik på tandvård
        if ctx.table.category != "reference" and any(c.generator.startswith(("finance.cost_center", "finance.administration")) for c in ctx.table.columns):
            _, name, adm, _ = cost_center(ctx, group)
            code = ("400" if adm == "Folktandvården" else "100" if name.startswith("Hälsocentralen") else "300" if "psykiatri" in name
                    else "200" if adm.startswith("Hälso-") else "950" if adm == "Regionstaben" else "800" if name == "Kollektivtrafik" else "700")
            if ctx.rng.random() < 0.85:
                return next(a for a in ACTIVITIES if a[0] == code)
        return _pick(ctx, ACTIVITIES)
    return ctx.entity("activity:" + (group or ""), build)


def employee(ctx, group=""):
    def build():
        rng = ctx.rng
        title, category, lo, hi, _ = _pick(ctx, TITLES)
        grade = _weighted(rng, [g[0] for g in GRADES], [g[1] for g in GRADES])
        return {"title": title, "category": category, "salary": round(rng.uniform(lo, hi) / 100) * 100, "grade": grade,
                "form": _weighted(rng, [f[0] for f in EMPLOYMENT_FORMS], [f[1] for f in EMPLOYMENT_FORMS])}
    return ctx.entity("employee:" + (group or ""), build)


_FRONT = [q * 10 + n for q in (1, 2, 3, 4) for n in (1, 2, 3)]
_BACK = [q * 10 + n for q in (1, 2, 3, 4) for n in (4, 5, 6, 7)]


def dental(ctx, group=""):
    def build():
        rng = ctx.rng
        code, text, lo, hi, surfaces, where, diag, _ = _pick(ctx, DENTAL_PROCEDURES)
        tooth = None if where is None else rng.choice(_FRONT if where == "fram" else _BACK if where == "bak" else _FRONT + _BACK)
        surface = None
        if surfaces:
            pool = ["M", "D", "B", "L"] if where == "fram" else ["M", "O", "D", "B", "L"]
            n = surfaces if surfaces < 3 else rng.choice([3, 3, 4])
            chosen = set(rng.sample(pool, min(n, len(pool))))
            surface = "".join(s for s in pool if s in chosen)
        return {"code": code, "text": text, "price": round(rng.uniform(lo, hi) / 5) * 5, "tooth": tooth, "surface": surface,
                "diag": diag, "diag_text": _DIAG_TEXT[diag]}
    return ctx.entity("dental:" + (group or ""), build)


def _simple(key, label, group_label, entity, field, help):
    @register(key, label, group_label, [GROUP], help=help)
    def gen(ctx, p):
        e = entity(ctx, p["group"])
        return e[field]
    return gen


_EK = "Exempel på kontoplan, ansvar och verksamhet – inte regionens riktiga kodplan. Kod och benämning hör ihop på raden. I kodtabeller delas koderna ut i ordning."


@register("finance.account_code", "Konto: kontonummer", "Ekonomi", [
    Param("scope", "Kontoklasser", "select", ACCOUNT_SCOPES[0], ACCOUNT_SCOPES, help="Leverantörsfakturor bokförs på kostnadskonton. Gäller alla kontokolumner på raden."), GROUP,
], help=_EK)
def gen_account_code(ctx, p):
    return account(ctx, p["group"])[0]


_simple("finance.account_name", "Konto: benämning", "Ekonomi", account, 1, _EK)
_simple("finance.cost_center_code", "Ansvar / kostnadsställe: kod", "Ekonomi", cost_center, 0, _EK)
_simple("finance.cost_center_name", "Ansvar / kostnadsställe: benämning", "Ekonomi", cost_center, 1, _EK)
_simple("finance.administration", "Förvaltning", "Ekonomi", cost_center, 2, _EK)
_simple("finance.activity_code", "Verksamhet: kod", "Ekonomi", activity, 0, _EK)
_simple("finance.activity_name", "Verksamhet: benämning", "Ekonomi", activity, 1, _EK)


@register("finance.account_class", "Konto: kontoklass", "Ekonomi", [GROUP], help=_EK)
def gen_account_class(ctx, p):
    code = account(ctx, p["group"])[0]
    return f"{code[0]} {ACCOUNT_CLASSES.get(code[0], '')}".strip()


@register("finance.amount", "Belopp (rimligt för kontot)", "Ekonomi", [
    Param("factor", "Skalfaktor", "float", 1.0, help="Multiplicerar beloppen, t.ex. 12 för årsbudget eller 0.1 för små enheter."), GROUP,
], help="Beloppets storlek följer kontot på samma rad: löner och köpt vård ger stora belopp, kontorsmaterial små.")
def gen_amount(ctx, p):
    _, _, lo, hi, _ = account(ctx, p["group"])
    return round((lo + (hi - lo) * ctx.rng.betavariate(1.3, 4)) * float(p["factor"]), 2)


PERIOD_FORMATS = ["ÅÅÅÅMM", "ÅÅÅÅ-MM", "MM"]


@register("finance.period", "Redovisningsperiod", "Ekonomi", [
    Param("start", "Från", "str", "-2y", help="ÅÅÅÅ-MM-DD, 'idag' eller relativt: -2y, -6m"),
    Param("end", "Till", "str", "idag"), Param("format", "Format", "select", PERIOD_FORMATS[0], PERIOD_FORMATS),
    Param("source", "Härled från datumkolumn (valfritt)", "column", "", help="Om angiven följer perioden datumet på raden."),
])
def gen_period(ctx, p):
    d = ctx.get(p["source"]) if p["source"] and ctx.has_column(p["source"]) else None
    if d is None or not hasattr(d, "year"):
        a, b = parse_date_spec(p["start"], ctx.today), parse_date_spec(p["end"], ctx.today)
        if b < a:
            a, b = b, a
        if ctx.since and ctx.since > a:
            a = ctx.since
        months = (b.year - a.year) * 12 + b.month - a.month
        m = a.year * 12 + a.month - 1 + ctx.rng.randint(0, max(0, months))
        year, month = divmod(m, 12)
        month += 1
    else:
        year, month = d.year, d.month
    fmt = str(p["format"])
    return f"{month:02d}" if fmt == "MM" else f"{year}-{month:02d}" if "-" in fmt else year * 100 + month


@register("finance.ocr", "OCR-nummer", "Ekonomi", [Param("digits", "Antal siffror", "int", 12)], help="Påhittat OCR-nummer med korrekt kontrollsiffra.")
def gen_ocr(ctx, p):
    n = max(2, int(p["digits"]))
    body = "".join(str(ctx.rng.randint(0, 9)) for _ in range(n - 1))
    padded = body if len(body) % 2 else "0" + body  # luhn_digit räknar från vänster med vikt 2 först
    return body + str(luhn_digit(padded))


_HR = "Exempel på befattningar och lönenivåer. Befattning, yrkeskategori och lön hör ihop på raden."
_simple("hr.title", "Befattning", "Personal", employee, "title", _HR)
_simple("hr.category", "Yrkeskategori", "Personal", employee, "category", _HR)
_simple("hr.salary", "Månadslön (rimlig för befattningen)", "Personal", employee, "salary", _HR)
_simple("hr.employment_form", "Anställningsform", "Personal", employee, "form", _HR)
_simple("hr.grade", "Sysselsättningsgrad (%)", "Personal", employee, "grade", _HR)

_TV = "Exempel på tandvårdsåtgärder med ungefärliga priser – inte gällande referensprislista. Åtgärd, tand, ytor, pris och diagnos hör ihop på raden."
_simple("dental.procedure_code", "Tandvårdsåtgärd: kod", "Tandvård", dental, "code", _TV)
_simple("dental.procedure_text", "Tandvårdsåtgärd: text", "Tandvård", dental, "text", _TV)
_simple("dental.price", "Tandvårdsåtgärd: pris", "Tandvård", dental, "price", _TV)
_simple("dental.tooth", "Tandnummer (11–48)", "Tandvård", dental, "tooth", _TV + " Undersökningar saknar tandnummer.")
_simple("dental.surface", "Tandytor (t.ex. MOD)", "Tandvård", dental, "surface", _TV + " Bara fyllningar har ytor.")


def _dental_diag(ctx, group):
    if ctx.table.category == "reference":
        return DENTAL_DIAGNOSES[(ctx.index + ctx.offset) % len(DENTAL_DIAGNOSES)]
    e = dental(ctx, group)
    return e["diag"], e["diag_text"]


@register("dental.diagnosis_code", "Tandvårdsdiagnos: kod", "Tandvård", [GROUP], help=_TV)
def gen_dental_diag_code(ctx, p):
    return _dental_diag(ctx, p["group"])[0]


@register("dental.diagnosis_text", "Tandvårdsdiagnos: text", "Tandvård", [GROUP], help=_TV)
def gen_dental_diag_text(ctx, p):
    return _dental_diag(ctx, p["group"])[1]


@register("dental.clinic", "Tandvårdsklinik", "Tandvård", [], help="Folktandvårdskliniker på orter i länet.")
def gen_dental_clinic(ctx, p):
    if ctx.table.category in ("reference", "location"):  # i en kliniktabell: en klinik per rad
        return _FTV[(ctx.index + ctx.offset) % len(_FTV)]
    return ctx.rng.choice(_FTV)


# generatorer vars värde kan styra vilken rad i en kodtabell som en främmande nyckel pekar på
GUIDED = ("care.", "finance.account_code", "finance.cost_center_code", "finance.activity_code", "dental.procedure_code",
          "dental.diagnosis_code", "hr.title")
# kodtabellernas storlek per generatorprefix
SIZES = {"finance.account": len(ACCOUNTS), "finance.cost_center": len(COST_CENTERS), "finance.administration": len(COST_CENTERS),
         "finance.activity": len(ACTIVITIES), "hr.": len(TITLES), "dental.clinic": len(_FTV), "dental.diagnosis": len(DENTAL_DIAGNOSES),
         "dental.": len(DENTAL_PROCEDURES)}

vocab.PRESETS.update(REGION_PRESETS)
_g._build_labels()
