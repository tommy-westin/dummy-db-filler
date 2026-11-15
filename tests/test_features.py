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
CREATE TABLE dbo.Kund (
    KundID int IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Kundnamn nvarchar(80) NOT NULL,
    Kundtyp nvarchar(20) NOT NULL CONSTRAINT CK_Kundtyp CHECK (Kundtyp IN ('Privat', 'Företag')),
    Registrerad date NOT NULL,
    Kreditgrans decimal(10,2) NOT NULL CHECK ([Kreditgrans] >= 0 AND [Kreditgrans] <= 5000),
    Sparrad bit NOT NULL DEFAULT ((0)),
    Status varchar(10) NOT NULL DEFAULT ('Aktiv'),
    CONSTRAINT CK_Status CHECK ([Status]='Vilande' OR [Status]='Aktiv')
);
CREATE TABLE dbo.KundOrder (
    OrderID int NOT NULL PRIMARY KEY,
    KundID int NOT NULL REFERENCES dbo.Kund (KundID),
    Orderdatum date NOT NULL,
    Betalsatt nvarchar(20) NULL
);
CREATE TABLE dbo.Orderrad (
    OrderradID int NOT NULL PRIMARY KEY,
    OrderID int NOT NULL REFERENCES dbo.KundOrder (OrderID),
    Radnr int NOT NULL,
    Antal int NOT NULL CHECK (Antal BETWEEN 1 AND 4),
    Pris decimal(10,2) NOT NULL,
    Leveransdatum date NULL
);
CREATE TABLE dbo.DimKund (
    KundKey int IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Kundnummer varchar(20) NOT NULL,
    Kundnamn nvarchar(80) NOT NULL,
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
    kund = p.table("dbo.Kund")
    assert len(kund.checks) == 3 and kund.column("Status").default == "('Aktiv')"
    checks = parse_checks(kund)
    assert checks["Kundtyp"]["values"] == ["Privat", "Företag"] and checks["Status"]["values"] == ["Vilande", "Aktiv"]
    assert checks["Kreditgrans"] == {"min": 0.0, "max": 5000.0}
    res = generate(p)
    kunder = rows_of(res, "dbo.Kund")
    assert {k["Kundtyp"] for k in kunder} == {"Privat", "Företag"}
    status = Counter(k["Status"] for k in kunder)
    assert set(status) == {"Aktiv", "Vilande"} and status["Aktiv"] > status["Vilande"]  # standardvärdet väger tyngst
    assert all(0 <= k["Kreditgrans"] <= 5000 for k in kunder)
    assert sum(k["Sparrad"] for k in kunder) < len(kunder) * 0.3
    assert all(1 <= r["Antal"] <= 4 for r in rows_of(res, "dbo.Orderrad"))


def test_children_per_parent_and_time_logic():
    p = sales()
    fk = p.table("dbo.Orderrad").foreign_keys[0]
    assert (fk.per_parent_min, fk.per_parent_max) == (1, 5)
    assert p.table("dbo.Orderrad").column("Radnr").generator == "sequence.per_parent"
    assert 400 <= estimated_rows(p, p.table("dbo.Orderrad")) <= 800
    res = generate(p)
    order = {o["OrderID"]: o for o in rows_of(res, "dbo.KundOrder")}
    per = defaultdict(list)
    for r in rows_of(res, "dbo.Orderrad"):
        per[r["OrderID"]].append(r)
    assert set(per) == set(order) and all(1 <= len(v) <= 5 for v in per.values())
    assert all([r["Radnr"] for r in v] == list(range(1, len(v) + 1)) for v in per.values())
    # ordrar per kund bildar ett förlopp i tiden och ligger aldrig före kundens registrering... (floor saknas här: ingen födelsedatumkolumn)
    assert p.table("dbo.KundOrder").column("Orderdatum").generator == "date.chain"
    per_kund = defaultdict(list)
    for o in order.values():
        per_kund[o["KundID"]].append(o["Orderdatum"])
    assert all(v == sorted(v) for v in per_kund.values())
    # leveransdatum hör till raden; orderradens datum hamnar aldrig före orderns
    p.table("dbo.Orderrad").column("Leveransdatum").generator = "date.after_parent"
    p.table("dbo.Orderrad").column("Leveransdatum").params = {"via": "OrderID", "column": "Orderdatum", "min_days": 1, "max_days": 9}
    res = generate(p)
    for r in rows_of(res, "dbo.Orderrad"):
        if r["Leveransdatum"] is not None:
            assert timedelta(days=1) <= r["Leveransdatum"] - order[r["OrderID"]]["Orderdatum"] <= timedelta(days=9)


def test_conditional_values_and_scenarios():
    p = sales()
    order = p.table("dbo.KundOrder")
    order.columns.append(Column.from_type("Kundtyp", "nvarchar(20)", custom=True))
    c = order.column("Kundtyp")
    c.generator, c.params = "parent.lookup", {"via": "KundID", "column": "Kundtyp"}
    b = order.column("Betalsatt")
    b.generator, b.params = "choice.by", {"column": "Kundtyp", "mapping": "Privat: Kort | 60, Swish | 40\nFöretag: Faktura\n*: Kontant"}
    res = generate(p)
    seen = defaultdict(set)
    for o in rows_of(res, "dbo.KundOrder"):
        seen[o["Kundtyp"]].add(o["Betalsatt"])
    assert seen["Företag"] == {"Faktura"} and seen["Privat"] == {"Kort", "Swish"}
    small = generate(p, scale=0.1)
    assert len(small.data["dbo.Kund"].rows) == 20 and len(small.data["dbo.KundOrder"].rows) == 20


def test_history_scd2():
    p = sales()
    dim = p.table("dbo.DimKund")
    assert dim.history["enabled"] and dim.history["from"] == "GiltigFran" and dim.history["current"] == "ArAktuell"
    dim.history.update(min=2, max=4)
    dim.rows = 60
    res = generate(p)
    rows = rows_of(res, "dbo.DimKund")
    by_key = defaultdict(list)
    for r in rows:
        by_key[r["Kundnummer"]].append(r)
    assert len(by_key) == 60 and len(rows) > 60
    assert len({r["KundKey"] for r in rows}) == len(rows)  # surrogatnyckeln är unik
    for versions in by_key.values():
        assert len({v["Kundnamn"] for v in versions}) == 1  # stabila attribut följer med
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
    n_orders = len(first.data["KundOrder"].rows)
    n_lines = len(first.data["Orderrad"].rows)
    since = date.today() - timedelta(days=1)
    ap = dbio.prepare_append(eng, p, {"KundOrder", "Orderrad"}, since, 0.2)
    assert ap.counts["KundOrder"] == n_orders and ap.maxima["KundOrder"]["OrderID"] == n_orders
    res = generate(p, append=ap)
    assert res.order == ["KundOrder", "Orderrad"] and "Kund" in res.existing
    new = rows_of(res, "KundOrder")
    assert len(new) == 10 and min(o["OrderID"] for o in new) == n_orders + 1
    assert all(o["Orderdatum"] >= since for o in new)
    kund_ids = set(first.data["Kund"].column_values("KundID"))
    assert all(o["KundID"] in kund_ids for o in new)
    lines = rows_of(res, "Orderrad")
    assert {r["OrderID"] for r in lines} == {o["OrderID"] for o in new} and min(r["OrderradID"] for r in lines) == n_lines + 1
    dbio.write_database(eng, res)
    with eng.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM KundOrder")).scalar() == n_orders + 10
        assert conn.execute(sa.text("SELECT COUNT(*) FROM Orderrad o JOIN KundOrder k ON k.OrderID = o.OrderID")).scalar() == n_lines + len(lines)


def test_dirty_data_and_quality_report():
    p = sales()
    order = p.table("dbo.KundOrder")
    order.foreign_keys[0].source = "manual"  # relation som inte finns i databasen -> föräldralösa tillåts
    p.dirty = {"tables": ["dbo.Kund", "dbo.KundOrder"], "pct": 10, "kinds": ["whitespace", "case", "duplicates", "orphans"]}
    res = generate(p)
    assert res.dirty_log
    names = res.data["dbo.Kund"].column_values("Kundnamn")
    assert any(n != n.strip() for n in names)
    assert len(set(res.data["dbo.Kund"].column_values("KundID"))) == len(names)  # nycklar rörs inte
    rel = {r["Tabell"]: r for r in quality.relation_report(res)}
    assert rel["dbo.KundOrder"]["Föräldralösa"] > 0 and rel["dbo.Orderrad"]["Föräldralösa"] == 0
    assert all(r["Dubbletter"] == 0 for r in quality.key_report(res))
    p.dirty = {}
    clean = generate(p)
    assert not clean.dirty_log
    cols = {r["Kolumn"]: r for r in quality.column_report(clean.data["dbo.Kund"])}
    assert cols["Kundtyp"]["Unika värden"] == 2 and cols["KundID"]["Vanligaste värden"] == "alla unika"


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
    assert "FROM [dbo].[Kund] WHERE [Kundtyp] IS NOT NULL GROUP BY [Kundtyp] HAVING COUNT_BIG(*) >= 5" in sql
    assert "[Kundnamn] IS NOT NULL GROUP BY" not in sql and "N'KundID', 'value'" not in sql  # identifierande kolumner och nycklar ingår inte
    csv = ("tabell;kolumn;matt;varde;antal\n"
           "dbo.Kund;;rows;NULL;40000\n"
           "dbo.Kund;Kundtyp;value;Privat;36000\ndbo.Kund;Kundtyp;value;Företag;4000\n"
           "dbo.Kund;Kreditgrans;min;100.000000;NULL\ndbo.Kund;Kreditgrans;max;900.000000;NULL\ndbo.Kund;Kreditgrans;avg;300.000000;NULL\n"
           "dbo.Kund;Registrerad;min;2019-02-01;NULL\ndbo.Kund;Registrerad;max;2024-06-30;NULL\n"
           "dbo.KundOrder;;rows;NULL;100000\ndbo.KundOrder;Betalsatt;null;NULL;25000\n")
    done = prodprofile.apply_profile(p, prodprofile.parse_profile(csv), True, 0.01)
    assert done["radantal"] == 2 and done["värdefördelningar"] == 1 and done["talintervall"] == 1 and done["datumintervall"] == 1
    assert p.table("dbo.Kund").rows == 400 and p.table("dbo.KundOrder").column("Betalsatt").null_pct == 25.0
    res = generate(p)
    kunder = rows_of(res, "dbo.Kund")
    typ = Counter(k["Kundtyp"] for k in kunder)
    assert typ["Privat"] > 300 and all(100 <= k["Kreditgrans"] <= 900 for k in kunder)
    assert all(date(2019, 2, 1) <= k["Registrerad"] <= date(2024, 6, 30) for k in kunder)


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
    assert len((tmp_path / "csv" / "Kund.csv").read_text(encoding="utf-8-sig").splitlines()) == 21
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    assert main(["generate", str(path), "--target", "db", "--url", url, "--create-missing"]) == 0
    assert main(["generate", str(path), "--target", "db", "--url", url, "--append", "--fraction", "10"]) == 0
    with sa.create_engine(url).connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM KundOrder")).scalar() == 220
    assert main(["profile-sql", str(path), "--out", str(tmp_path / "profil.sql")]) == 0
    assert "COUNT_BIG" in (tmp_path / "profil.sql").read_text(encoding="utf-8-sig")
