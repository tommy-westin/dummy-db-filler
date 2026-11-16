"""Tester för: barn per förälder, tidslogik, CHECK, scenarier, historik, inkrementellt, smutsig data,
förlopp, samband, kodverk, testpersonnummer, profil, kvalitetsrapport, regler och kommandorad."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import sqlalchemy as sa

from dummyfiller import dbio, prodprofile, quality, rules
from dummyfiller.__main__ import main
from dummyfiller.ddl import parse_ddl
from dummyfiller.engine import estimated_rows, generate
from dummyfiller.inference import infer_project, infer_table, parse_checks
from dummyfiller.model import Column, ForeignKey, Project, Table

ROOT = Path(__file__).resolve().parent.parent

SALES = """
CREATE TABLE dbo.Leverantor (
    LeverantorID int IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Leverantorsnamn nvarchar(80) NOT NULL,
    Leverantorstyp nvarchar(20) NOT NULL CONSTRAINT CK_Leverantorstyp CHECK (Leverantorstyp IN ('Företag', 'Myndighet')),
    Registrerad date NOT NULL,
    Beloppsgrans decimal(10,2) NOT NULL CHECK ([Beloppsgrans] >= 0 AND [Beloppsgrans] <= 5000),
    Sparrad bit NOT NULL DEFAULT ((0)),
    Status varchar(10) NOT NULL DEFAULT ('Aktiv'),
    CONSTRAINT CK_Status CHECK ([Status]='Vilande' OR [Status]='Aktiv')
);
CREATE TABLE dbo.Leverantorsfaktura (
    FakturaID int NOT NULL PRIMARY KEY,
    LeverantorID int NOT NULL REFERENCES dbo.Leverantor (LeverantorID),
    Fakturadatum date NOT NULL,
    Betalvillkor nvarchar(20) NULL
);
CREATE TABLE dbo.Fakturarad (
    FakturaradID int NOT NULL PRIMARY KEY,
    FakturaID int NOT NULL REFERENCES dbo.Leverantorsfaktura (FakturaID),
    Radnr int NOT NULL,
    Antal int NOT NULL CHECK (Antal BETWEEN 1 AND 4),
    Belopp decimal(10,2) NOT NULL,
    Bokforingsdatum date NULL
);
CREATE TABLE dbo.DimLeverantor (
    LeverantorKey int IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Leverantorsnummer varchar(20) NOT NULL,
    Leverantorsnamn nvarchar(80) NOT NULL,
    Ort nvarchar(60) NULL,
    Telefon varchar(20) NULL,
    GiltigFran date NOT NULL,
    GiltigTill date NULL,
    ArAktuell bit NOT NULL
);
"""


def sales() -> Project:
    tables, warns = parse_ddl(SALES)
    assert not warns
    p = Project(tables=tables)
    infer_project(p)
    for t in p.tables:
        t.rows = min(t.rows, 200)
    return p


def no_schema(p: Project) -> Project:
    """SQLite saknar scheman: gör om dbo.Tabell till Tabell."""
    for t in p.tables:
        t.schema = ""
        for fk in t.foreign_keys:
            fk.ref_table = fk.ref_table.split(".")[-1]
    return p


def rows_of(res, key):
    d = res.data[key]
    return [dict(zip(d.columns, r)) for r in d.rows]


def test_checks_and_defaults():
    p = sales()
    kund = p.table("dbo.Leverantor")
    assert len(kund.checks) == 3 and kund.column("Status").default == "('Aktiv')"
    checks = parse_checks(kund)
    assert checks["Leverantorstyp"]["values"] == ["Företag", "Myndighet"] and checks["Status"]["values"] == ["Vilande", "Aktiv"]
    assert checks["Beloppsgrans"] == {"min": 0.0, "max": 5000.0}
    res = generate(p)
    leverantorer = rows_of(res, "dbo.Leverantor")
    assert {k["Leverantorstyp"] for k in leverantorer} == {"Företag", "Myndighet"}
    status = Counter(k["Status"] for k in leverantorer)
    assert set(status) == {"Aktiv", "Vilande"} and status["Aktiv"] > status["Vilande"]  # standardvärdet väger tyngst
    assert all(0 <= k["Beloppsgrans"] <= 5000 for k in leverantorer)
    assert sum(k["Sparrad"] for k in leverantorer) < len(leverantorer) * 0.3
    assert all(1 <= r["Antal"] <= 4 for r in rows_of(res, "dbo.Fakturarad"))


def test_children_per_parent_and_time_logic():
    p = sales()
    fk = p.table("dbo.Fakturarad").foreign_keys[0]
    assert (fk.per_parent_min, fk.per_parent_max) == (1, 5)
    assert p.table("dbo.Fakturarad").column("Radnr").generator == "sequence.per_parent"
    assert 400 <= estimated_rows(p, p.table("dbo.Fakturarad")) <= 800
    res = generate(p)
    order = {o["FakturaID"]: o for o in rows_of(res, "dbo.Leverantorsfaktura")}
    per = defaultdict(list)
    for r in rows_of(res, "dbo.Fakturarad"):
        per[r["FakturaID"]].append(r)
    assert set(per) == set(order) and all(1 <= len(v) <= 5 for v in per.values())
    assert all([r["Radnr"] for r in v] == list(range(1, len(v) + 1)) for v in per.values())
    # fakturor per leverantör bildar ett förlopp i tiden
    assert p.table("dbo.Leverantorsfaktura").column("Fakturadatum").generator == "date.chain"
    per_lev = defaultdict(list)
    for o in order.values():
        per_lev[o["LeverantorID"]].append(o["Fakturadatum"])
    assert all(v == sorted(v) for v in per_lev.values())
    # fakturaradens bokföringsdatum hamnar aldrig före fakturans datum
    p.table("dbo.Fakturarad").column("Bokforingsdatum").generator = "date.after_parent"
    p.table("dbo.Fakturarad").column("Bokforingsdatum").params = {"via": "FakturaID", "column": "Fakturadatum", "min_days": 1, "max_days": 9}
    res = generate(p)
    for r in rows_of(res, "dbo.Fakturarad"):
        if r["Bokforingsdatum"] is not None:
            assert timedelta(days=1) <= r["Bokforingsdatum"] - order[r["FakturaID"]]["Fakturadatum"] <= timedelta(days=9)


def test_conditional_values_and_scenarios():
    p = sales()
    order = p.table("dbo.Leverantorsfaktura")
    order.columns.append(Column.from_type("Leverantorstyp", "nvarchar(20)", custom=True))
    c = order.column("Leverantorstyp")
    c.generator, c.params = "parent.lookup", {"via": "LeverantorID", "column": "Leverantorstyp"}
    b = order.column("Betalvillkor")
    b.generator, b.params = "choice.by", {"column": "Leverantorstyp", "mapping": "Företag: 30 dagar | 60, 20 dagar | 40\nMyndighet: 60 dagar\n*: Kontant"}
    res = generate(p)
    seen = defaultdict(set)
    for o in rows_of(res, "dbo.Leverantorsfaktura"):
        seen[o["Leverantorstyp"]].add(o["Betalvillkor"])
    assert seen["Myndighet"] == {"60 dagar"} and seen["Företag"] == {"30 dagar", "20 dagar"}
    small = generate(p, scale=0.1)
    assert len(small.data["dbo.Leverantor"].rows) == 10 and len(small.data["dbo.Leverantorsfaktura"].rows) == 20


def test_history_scd2():
    p = sales()
    dim = p.table("dbo.DimLeverantor")
    assert dim.history["enabled"] and dim.history["from"] == "GiltigFran" and dim.history["current"] == "ArAktuell"
    dim.history.update(min=2, max=4)
    dim.rows = 60
    res = generate(p)
    rows = rows_of(res, "dbo.DimLeverantor")
    by_key = defaultdict(list)
    for r in rows:
        by_key[r["Leverantorsnummer"]].append(r)
    assert len(by_key) == 60 and len(rows) > 60
    assert len({r["LeverantorKey"] for r in rows}) == len(rows)  # surrogatnyckeln är unik
    for versions in by_key.values():
        assert len({v["Leverantorsnamn"] for v in versions}) == 1  # stabila attribut följer med
        assert [v["ArAktuell"] for v in versions] == [False] * (len(versions) - 1) + [True]
        assert versions[-1]["GiltigTill"] is None
        for a, b in zip(versions, versions[1:]):
            assert a["GiltigTill"] == b["GiltigFran"] and a["GiltigFran"] < a["GiltigTill"]
    assert any(len({v["Ort"] for v in vs}) > 1 for vs in by_key.values())  # adressen ändras mellan versioner


def test_incremental_append(tmp_path):
    p = no_schema(sales())
    for t in p.tables:
        t.rows = 50
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    first = generate(p)
    dbio.write_database(eng, first, create_missing=True)
    n_orders = len(first.data["Leverantorsfaktura"].rows)
    n_lines = len(first.data["Fakturarad"].rows)
    since = date.today() - timedelta(days=1)
    ap = dbio.prepare_append(eng, p, {"Leverantorsfaktura", "Fakturarad"}, since, 0.2)
    assert ap.counts["Leverantorsfaktura"] == n_orders and ap.maxima["Leverantorsfaktura"]["FakturaID"] == n_orders
    res = generate(p, append=ap)
    assert res.order == ["Leverantorsfaktura", "Fakturarad"] and "Leverantor" in res.existing
    new = rows_of(res, "Leverantorsfaktura")
    assert len(new) == 10 and min(o["FakturaID"] for o in new) == n_orders + 1
    assert all(o["Fakturadatum"] >= since for o in new)
    lev_ids = set(first.data["Leverantor"].column_values("LeverantorID"))
    assert all(o["LeverantorID"] in lev_ids for o in new)
    lines = rows_of(res, "Fakturarad")
    assert {r["FakturaID"] for r in lines} == {o["FakturaID"] for o in new} and min(r["FakturaradID"] for r in lines) == n_lines + 1
    dbio.write_database(eng, res)
    with eng.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM Leverantorsfaktura")).scalar() == n_orders + 10
        assert conn.execute(sa.text("SELECT COUNT(*) FROM Fakturarad o JOIN Leverantorsfaktura k ON k.FakturaID = o.FakturaID")).scalar() == n_lines + len(lines)


def test_dirty_data_and_quality_report():
    p = sales()
    order = p.table("dbo.Leverantorsfaktura")
    order.foreign_keys[0].source = "manual"  # relation som inte finns i databasen -> föräldralösa tillåts
    p.dirty = {"tables": ["dbo.Leverantor", "dbo.Leverantorsfaktura"], "pct": 10, "kinds": ["whitespace", "case", "duplicates", "orphans"]}
    res = generate(p)
    assert res.dirty_log
    names = res.data["dbo.Leverantor"].column_values("Leverantorsnamn")
    assert any(n != n.strip() for n in names)
    assert len(set(res.data["dbo.Leverantor"].column_values("LeverantorID"))) == len(names)  # nycklar rörs inte
    rel = {r["Tabell"]: r for r in quality.relation_report(res)}
    assert rel["dbo.Leverantorsfaktura"]["Föräldralösa"] > 0 and rel["dbo.Fakturarad"]["Föräldralösa"] == 0
    assert all(r["Dubbletter"] == 0 for r in quality.key_report(res))
    p.dirty = {}
    clean = generate(p)
    assert not clean.dirty_log
    cols = {r["Kolumn"]: r for r in quality.column_report(clean.data["dbo.Leverantor"])}
    assert cols["Leverantorstyp"]["Unika värden"] == 2 and cols["LeverantorID"]["Vanligaste värden"] == "alla unika"


def care_project() -> Project:
    tables, _ = parse_ddl((ROOT / "exempel" / "vard.sql").read_text(encoding="utf-8"))
    p = Project(tables=tables)
    infer_project(p)
    return p


def test_care_pathways_and_correlations():
    p = care_project()
    res = generate(p)
    pat = {r["PatientID"]: r for r in rows_of(res, "dbo.Patient")}
    vk = {r["VardkontaktID"]: r for r in rows_of(res, "dbo.Vardkontakt")}
    per = defaultdict(list)
    for r in vk.values():
        assert r["Inskrivningsdatum"].date() >= pat[r["PatientID"]]["Fodelsedatum"]
        per[r["PatientID"]].append(r["Inskrivningsdatum"])
        stay = r["Utskrivningsdatum"] - r["Inskrivningsdatum"]
        assert (stay >= timedelta(days=1)) == (r["Kontakttyp"] == "Vårdtillfälle")
    assert all(v == sorted(v) for v in per.values())
    for r in rows_of(res, "dbo.Labbsvar"):
        if r["VardkontaktID"] is not None:
            k = vk[r["VardkontaktID"]]
            assert k["Inskrivningsdatum"] <= r["Provtagningsdatum"] <= k["Utskrivningsdatum"]
    diag = defaultdict(list)
    for r in rows_of(res, "dbo.VardkontaktDiagnos"):
        diag[r["VardkontaktID"]].append(r)
    assert all(v[0]["Diagnostyp"] == "Huvuddiagnos" and all(x["Diagnostyp"] == "Bidiagnos" for x in v[1:]) for v in diag.values())
    # kön och ålder styr diagnos
    for kid, ds in diag.items():
        person = pat[vk[kid]["PatientID"]]
        for d in ds:
            if d["DiagnosKod"] == "C61.9":
                assert person["Kon"] == "M"
            if d["DiagnosKod"] == "H66.9":
                assert (date.today() - person["Fodelsedatum"]).days // 365 <= 14
    # diagnos styr läkemedel: metformin ska vara klart vanligare vid diabetes än annars
    def share(code, drug):
        hit = [r for r in rows_of(res, "dbo.Lakemedelsordination") if diag[r["VardkontaktID"]][0]["DiagnosKod"] == code]
        return sum(r["Lakemedel"] == drug for r in hit) / max(len(hit), 1)
    assert share("E11.9", "Metformin") > 0.25 > share("J06.9", "Metformin")


def test_patient_level_chronic_conditions():
    """Steg C: kroniska sjukdomar hör till patienten och följer med i alla patientens kontakter, läkemedel och provsvar."""
    from statistics import mean

    from dummyfiller import care
    p = care_project()
    assert p.table("dbo.Vardkontakt").fk_for("PatientID").distribution == "need"
    res = generate(p)
    pat = res.data["dbo.Patient"]
    prof = {pid: care.patient_profile(p.seed, pat, i) for i, pid in enumerate(pat.column_values("PatientID"))}
    vk = {r["VardkontaktID"]: r for r in rows_of(res, "dbo.Vardkontakt")}
    for r in rows_of(res, "dbo.VardkontaktDiagnos"):  # ingen får en kronisk diagnos som hen inte har
        if r["DiagnosKod"] in care.CHRONIC:
            assert r["DiagnosKod"] in prof[vk[r["VardkontaktID"]]["PatientID"]]["chronic"]
    per = Counter(r["PatientID"] for r in vk.values())
    chronic = [per[k] for k, v in prof.items() if v["chronic"]]
    other = [per[k] for k, v in prof.items() if not v["chronic"]]
    assert mean(chronic) > 1.5 * mean(other)  # kroniker kommer oftare
    first = {}
    for r in sorted(vk.values(), key=lambda r: r["Inskrivningsdatum"]):
        first.setdefault(r["PatientID"], r["Besokstyp"])
    assert set(first.values()) == {"Nybesök"}
    labs = rows_of(res, "dbo.Labbsvar")
    assert all(r["PatientID"] == vk[r["VardkontaktID"]]["PatientID"] for r in labs if r["VardkontaktID"] is not None)  # samma patient
    diab = [float(r["Resultat"]) for r in labs if r["Analysnamn"] == "B-HbA1c" and "E11.9" in prof[r["PatientID"]]["chronic"]]
    rest = [float(r["Resultat"]) for r in labs if r["Analysnamn"] == "B-HbA1c" and not {"E11.9", "E10.9"} & set(prof[r["PatientID"]]["chronic"])]
    assert diab and rest and mean(diab) > mean(rest) + 8
    for pid, v in prof.items():  # patientens stående läkemedel har samma styrka varje gång
        for code, (d, strength) in v["drugs"].items():
            got = {r["Styrka"] for r in rows_of(res, "dbo.Lakemedelsordination") if vk[r["VardkontaktID"]]["PatientID"] == pid
                   and r["ATCKod"] == d[0] and r["Styrka"] != strength}
            assert not got or len(got) < 3
        break


def test_codebook_and_test_pnr():
    p = care_project()
    p.codebooks["diagnosis"] = [[f"X{n:02d}.{n % 10}", f"Extra diagnos {n}"] for n in range(60)] + [["I109", "Dubblett av inbyggd"]]
    infer_table(p.table("dbo.Diagnos"), p, set_rows=True)
    assert p.table("dbo.Diagnos").rows == 44 + 60
    p.value_lists["testpnr"] = [f"19{50 + i % 40:02d}{1 + i % 12:02d}{1 + i % 28:02d}{1000 + i:04d}" for i in range(600)] + ["ogiltig rad"]
    p.test_pnr_list = "testpnr"
    res = generate(p)
    codes = res.data["dbo.Diagnos"].column_values("DiagnosKod")
    assert len(codes) == 104 and len(set(codes)) == 104 and "X07.7" in codes
    allowed = {v[:8] + "-" + v[8:] for v in p.value_lists["testpnr"]}
    for r in rows_of(res, "dbo.Patient"):
        assert r["Personnummer"] in allowed
        assert r["Fodelsedatum"].strftime("%Y%m%d") == r["Personnummer"][:8]
        assert (int(r["Personnummer"][11]) % 2 == 1) == (r["Kon"] == "M")


def test_profile_sql_and_apply():
    p = sales()
    sql = prodprofile.build_profile_sql(p, 50, 5)
    assert "FROM [dbo].[Leverantor] WHERE [Leverantorstyp] IS NOT NULL GROUP BY [Leverantorstyp] HAVING COUNT_BIG(*) >= 5" in sql
    assert "[Leverantorsnamn] IS NOT NULL GROUP BY" not in sql and "N'LeverantorID', 'value'" not in sql  # identifierande kolumner och nycklar ingår inte
    csv = ("tabell;kolumn;matt;varde;antal\n"
           "dbo.Leverantor;;rows;NULL;40000\n"
           "dbo.Leverantor;Leverantorstyp;value;Företag;36000\ndbo.Leverantor;Leverantorstyp;value;Myndighet;4000\n"
           "dbo.Leverantor;Beloppsgrans;min;100.000000;NULL\ndbo.Leverantor;Beloppsgrans;max;900.000000;NULL\ndbo.Leverantor;Beloppsgrans;avg;300.000000;NULL\n"
           "dbo.Leverantor;Registrerad;min;2019-02-01;NULL\ndbo.Leverantor;Registrerad;max;2024-06-30;NULL\n"
           "dbo.Leverantorsfaktura;;rows;NULL;100000\ndbo.Leverantorsfaktura;Betalvillkor;null;NULL;25000\n")
    done = prodprofile.apply_profile(p, prodprofile.parse_profile(csv), True, 0.01)
    assert done["radantal"] == 2 and done["värdefördelningar"] == 1 and done["talintervall"] == 1 and done["datumintervall"] == 1
    assert p.table("dbo.Leverantor").rows == 400 and p.table("dbo.Leverantorsfaktura").column("Betalvillkor").null_pct == 25.0
    res = generate(p)
    leverantorer = rows_of(res, "dbo.Leverantor")
    typ = Counter(k["Leverantorstyp"] for k in leverantorer)
    assert typ["Företag"] > 300 and all(100 <= k["Beloppsgrans"] <= 900 for k in leverantorer)
    assert all(date(2019, 2, 1) <= k["Registrerad"] <= date(2024, 6, 30) for k in leverantorer)


def test_user_rules():
    rules.add_rule("*kod", "pattern", {"template": "ZZ-####"}, "string")
    t = Table("Sak", columns=[Column.from_type("SakID", "int", nullable=False), Column.from_type("Lagerkod", "varchar(10)"),
                              Column.from_type("Antalkod", "int")], primary_key=["SakID"], rows=5)
    p = Project(tables=[t])
    infer_project(p, set_rows=False)
    assert t.column("Lagerkod").generator == "pattern" and t.column("Lagerkod").params == {"template": "ZZ-####"}
    assert t.column("Antalkod").generator != "pattern"  # regeln gäller bara textkolumner
    rules.delete_rule(0)
    infer_table(t, p)
    assert t.column("Lagerkod").params != {"template": "ZZ-####"}


def test_cli(tmp_path, capsys):
    p = no_schema(sales())
    path = tmp_path / "p.yaml"
    p.save(path)
    assert main(["generate", str(path), "--target", "csv", "--out", str(tmp_path / "csv"), "--scenario", "liten"]) == 0
    assert "rader skrivna" in capsys.readouterr().out
    assert len((tmp_path / "csv" / "Leverantor.csv").read_text(encoding="utf-8-sig").splitlines()) == 11
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    assert main(["generate", str(path), "--target", "db", "--url", url, "--create-missing"]) == 0
    assert main(["generate", str(path), "--target", "db", "--url", url, "--append", "--fraction", "10"]) == 0
    with sa.create_engine(url).connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM Leverantorsfaktura")).scalar() == 220
    assert main(["profile-sql", str(path), "--out", str(tmp_path / "profil.sql")]) == 0
    assert "COUNT_BIG" in (tmp_path / "profil.sql").read_text(encoding="utf-8-sig")


def test_region_domains_examples():
    """Ekonomi, personal och tandvård: exempelscheman ska ge sammanhängande data utan varningar och utan gissningar."""
    tables = []
    for name in ("ekonomi", "personal", "tandvard"):
        t, warns = parse_ddl((ROOT / "exempel" / f"{name}.sql").read_text(encoding="utf-8"))
        assert not warns
        tables += t
    p = Project(tables=tables)
    infer_project(p)
    cats = {t.name: t.category for t in p.tables}
    assert cats["Konto"] == cats["Ansvar"] == cats["TandvardsAtgard"] == "reference" and cats["Leverantor"] == "company"
    assert cats["Budget"] == cats["Franvaro"] == cats["Tandbehandling"] == "transaction" and cats["Organisationsenhet"] == "location"
    assert "product" not in cats.values()
    for t in p.tables:
        t.rows = min(t.rows, 300)
    res = generate(p)
    assert not res.warnings
    konto = dict(zip(res.data["dbo.Konto"].column_values("Kontonr"), res.data["dbo.Konto"].column_values("Kontonamn")))
    assert konto["5011"] == "Månadslön" and len(konto) == 29
    for f in rows_of(res, "dbo.Leverantorsfaktura"):
        assert f["Fakturabelopp"] == f["BeloppExklMoms"] + f["Moms"] and (f["Forfallodatum"] - f["Fakturadatum"]).days == 30
        assert (f["Betalningsdatum"] is not None) == (f["Status"] == "Betald")
    for r in rows_of(res, "dbo.Fakturarad"):
        assert r["Kontonr"][0] != "3" and r["Radtext"] == konto[r["Kontonr"]]  # bara kostnadskonton; radtexten följer kontot
        assert r["Period"] == r["Bokforingsdatum"].year * 100 + r["Bokforingsdatum"].month
    for b in rows_of(res, "dbo.Budget"):
        assert b["Ar"] == b["Period"] // 100 and b["Avvikelse"] == b["Utfall"] - b["Budgetbelopp"]
    from dummyfiller.region import TITLES
    pay = {t[0]: (t[1], t[2], t[3]) for t in TITLES}
    for a in rows_of(res, "dbo.Anstalld"):
        cat, lo, hi = pay[a["Befattning"]]
        assert a["Yrkeskategori"] == cat and lo <= a["Manadslon"] <= hi
    assert all(0 <= (f["TillDatum"] - f["FranDatum"]).days <= 12 for f in rows_of(res, "dbo.Franvaro"))
    codes = set(res.data["dbo.TandvardsAtgard"].column_values("Atgardskod"))
    for b in rows_of(res, "dbo.Tandbehandling"):
        assert b["Atgardskod"] in codes
        if b["Atgardskod"] in ("704", "705", "706"):
            assert b["Tandnummer"] % 10 >= 4 and len(b["Tandyta"]) >= int(b["Atgardskod"]) - 703
        if b["Atgardskod"] in ("101", "111"):
            assert b["Tandnummer"] is None and b["Tandyta"] is None
    orter = Counter(res.data["dbo.Tandvardspatient"].column_values("Ort"))
    assert orter.most_common(1)[0][0] == "Östersund"
