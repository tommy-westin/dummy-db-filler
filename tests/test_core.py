from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from dummyfiller import dbio, export, valuelists
from dummyfiller.ddl import parse_ddl
from dummyfiller.engine import generate, load_order
from dummyfiller.generators import luhn_digit
from dummyfiller.inference import infer_project, infer_table, suggest_relations
from dummyfiller.model import Column, ForeignKey, Project, Table, merge_tables

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def care() -> Project:
    tables, warns = parse_ddl((ROOT / "exempel" / "vard.sql").read_text(encoding="utf-8"))
    assert not warns
    p = Project(tables=tables)
    infer_project(p)
    for t in p.tables:
        t.rows = min(t.rows, 300)
    return p


def check_integrity(p: Project, res):
    for key, data in res.data.items():
        t = data.table
        for u in [t.primary_key] + t.uniques:
            if u:
                keys = [tuple(r[data.colidx[c]] for c in u) for r in data.rows]
                keys = [k for k in keys if None not in k]
                assert len(keys) == len(set(keys)), f"dubbletter i {key} {u}"
        for fk in t.foreign_keys:
            parent = res.data[fk.ref_table]
            valid = {tuple(r[parent.colidx[c]] for c in fk.ref_columns) for r in parent.rows}
            for r in data.rows:
                k = tuple(r[data.colidx[c]] for c in fk.columns)
                assert None in k or k in valid, f"{key}.{fk.columns} pekar på saknad rad {k}"
        for c in t.columns:
            if not c.computed and not c.nullable:
                assert None not in data.column_values(c.name), f"NULL i {key}.{c.name}"


def test_ddl_parse(care):
    t = care.table("dbo.Patient")
    assert t.primary_key == ["PatientID"] and ["Personnummer"] in t.uniques
    assert t.column("PatientID").identity and t.column("RadVersion").computed
    assert t.column("Skapad").kind == "datetime" and t.column("Epost").length == 120
    assert [f.ref_table for f in t.foreign_keys] == ["dbo.Vardenhet"]
    assert care.table("dbo.VardkontaktDiagnos").primary_key == ["VardkontaktID", "DiagnosKod"]
    assert care.table("dbo.Personal").primary_key == ["PersonalID"]
    assert care.table("dbo.Vardkontakt").column("Anteckning").length is None


def test_categories_and_inference(care):
    cats = {t.name: t.category for t in care.tables}
    assert cats == {"Vardenhet": "location", "Patient": "person", "Personal": "person", "Diagnos": "reference",
                    "Vardkontakt": "transaction", "VardkontaktDiagnos": "bridge", "Lakemedelsordination": "transaction",
                    "Labbsvar": "transaction", "DimDatum": "calendar"}
    gen = {c.name: c.generator for c in care.table("dbo.Patient").columns}
    assert gen["Personnummer"] == "person.personnummer" and gen["Postnummer"] == "address.postcode"
    assert care.table("dbo.Labbsvar").column("Resultat").generator == "care.lab_value"


def test_generate_integrity_and_coherence(care):
    res = generate(care)
    assert res.order.index("dbo.Patient") < res.order.index("dbo.Vardkontakt") < res.order.index("dbo.Labbsvar")
    check_integrity(care, res)
    pat = res.data["dbo.Patient"]
    assert "RadVersion" not in pat.columns
    for r in pat.rows:
        row = dict(zip(pat.columns, r))
        pnr = row["Personnummer"]
        assert len(pnr) == 13 and pnr[:8] == row["Fodelsedatum"].strftime("%Y%m%d")
        assert luhn_digit(pnr[2:8] + pnr[9:12]) == int(pnr[12])
        assert (int(pnr[11]) % 2 == 1) == (row["Kon"] == "M")
    vk = res.data["dbo.Vardkontakt"]
    for r in vk.rows:
        row = dict(zip(vk.columns, r))
        assert row["Utskrivningsdatum"] is None or row["Utskrivningsdatum"] >= row["Inskrivningsdatum"]
    dim = res.data["dbo.DimDatum"]
    for r in dim.rows:
        row = dict(zip(dim.columns, r))
        d = row["Datum"]
        assert row["DatumID"] == d.year * 10000 + d.month * 100 + d.day and row["Ar"] == d.year and row["Manad"] == d.month
    lab = res.data["dbo.Labbsvar"]
    for r in lab.rows:
        row = dict(zip(lab.columns, r))
        assert (row["Avvikelseflagga"] == "H") == (row["Resultat"] > row["ReferensMax"])
    # självrelation: chef finns alltid bland tidigare rader
    per = res.data["dbo.Personal"]
    ids = per.column_values("PersonalID")
    assert all(c is None or c in ids for c in per.column_values("ChefID"))


def test_deterministic(care):
    a, b = generate(care), generate(care)
    assert a.data["dbo.Patient"].rows == b.data["dbo.Patient"].rows
    care.seed = 7
    assert generate(care).data["dbo.Patient"].rows != a.data["dbo.Patient"].rows


def test_cycle_and_custom_generators():
    a = Table("A", columns=[Column.from_type("id", "int", nullable=False), Column.from_type("b_id", "int", nullable=True),
                            Column.from_type("antal", "int"), Column.from_type("pris", "decimal(10,2)"),
                            Column.from_type("summa", "decimal(12,2)"), Column.from_type("kod", "varchar(10)")],
              primary_key=["id"], rows=50)
    b = Table("B", columns=[Column.from_type("id", "int", nullable=False), Column.from_type("a_id", "int", nullable=False),
                            Column.from_type("a_kod", "varchar(10)")],
              primary_key=["id"], rows=80)
    a.foreign_keys.append(ForeignKey(["b_id"], "dbo.B", ["id"]))
    b.foreign_keys.append(ForeignKey(["a_id"], "dbo.A", ["id"]))
    p = Project(tables=[a, b])
    infer_project(p, set_rows=False)
    a.column("summa").generator, a.column("summa").params = "expression", {"expr": "round(antal * pris, 2)"}
    a.column("kod").generator, a.column("kod").params = "pattern", {"template": "K-{seq:04}"}
    b.column("a_kod").generator, b.column("a_kod").params = "parent.lookup", {"via": "a_id", "column": "kod"}
    order, broken = load_order(p, ["dbo.A", "dbo.B"])
    assert order == ["dbo.A", "dbo.B"] and len(broken) == 1
    res = generate(p)
    da, db = res.data["dbo.A"], res.data["dbo.B"]
    assert set(da.column_values("b_id")) == {None}
    for r in da.rows:
        row = dict(zip(da.columns, r))
        assert abs(float(row["summa"]) - float(row["antal"]) * float(row["pris"])) < 0.01
    kod = dict(zip(da.column_values("id"), da.column_values("kod")))
    assert all(kod[r[db.colidx["a_id"]]] == r[db.colidx["a_kod"]] for r in db.rows)
    with pytest.raises(ValueError):
        from dummyfiller.generators import compile_expression
        compile_expression("__import__('os').system('x')")


def test_value_lists_and_merge():
    lists = valuelists.parse_file("koder.csv", "Kod;Namn\nAB-1234;Alfa\nCD-9876;Beta\n".encode())
    assert lists == {"koder:Kod": ["AB-1234", "CD-9876"], "koder:Namn": ["Alfa", "Beta"]}
    assert valuelists.parse_file("orter.txt", b"Lund\nUme\xc3\xa5\n") == {"orter": ["Lund", "Umeå"]}
    t = Table("X", columns=[Column.from_type("id", "int", nullable=False), Column.from_type("kod", "varchar(20)"),
                            Column.from_type("namn", "varchar(20)"), Column.from_type("ny", "varchar(7)")], primary_key=["id"], rows=40)
    p = Project(tables=[t], value_lists=lists)
    infer_project(p, set_rows=False)
    for name, params in (("kod", {"list": "koder:Kod", "linked": True}), ("namn", {"list": "koder:Namn", "linked": True}),
                         ("ny", {"list": "koder:Kod", "mode": "Härma mönstret (nya värden med samma form)"})):
        c = t.column(name)
        c.generator, c.params, c.manual = "list", params, True
    res = generate(p)
    d = res.data["dbo.X"]
    pairs = set(zip(d.column_values("kod"), d.column_values("namn")))
    assert pairs == {("AB-1234", "Alfa"), ("CD-9876", "Beta")}
    import re
    assert all(re.fullmatch(r"[A-Z]{2}-\d{4}", v) for v in d.column_values("ny"))
    # ny inläsning av schemat behåller manuella val
    t2 = Table("X", columns=[Column.from_type("id", "int", nullable=False), Column.from_type("kod", "varchar(20)")], primary_key=["id"])
    merge_tables(p, [t2])
    infer_table(t2, p)
    assert p.table("dbo.X").column("kod").generator == "list"


def test_suggest_relations():
    dim = Table("DimPatient", columns=[Column.from_type("PatientKey", "int", nullable=False)], primary_key=["PatientKey"])
    fact = Table("FactVardkontakt", columns=[Column.from_type("VardkontaktKey", "int", nullable=False), Column.from_type("PatientKey", "int")], primary_key=["VardkontaktKey"])
    assert suggest_relations(Project(tables=[dim, fact])) == [("dbo.FactVardkontakt", "PatientKey", "dbo.DimPatient", "PatientKey")]


def test_sqlite_roundtrip_and_exports(care, tmp_path):
    # egen tabell + kolumn som inte finns i databasen
    eng = sa.create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with eng.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
        conn.execute(sa.text("CREATE TABLE leverantor (leverantor_id INTEGER PRIMARY KEY, namn VARCHAR(80) NOT NULL, epost VARCHAR(120), skapad DATETIME)"))
        conn.execute(sa.text("CREATE TABLE faktura (faktura_id INTEGER PRIMARY KEY, leverantor_id INTEGER NOT NULL REFERENCES leverantor(leverantor_id), "
                             "fakturadatum DATE NOT NULL, belopp NUMERIC(12,2), status VARCHAR(20))"))
    tables = dbio.reflect(eng)
    p = Project(tables=tables)
    infer_project(p)
    assert p.table("faktura").foreign_keys[0].ref_table == "leverantor"
    extra = Table("extra", schema="", custom=True, columns=[Column.from_type("id", "int", nullable=False), Column.from_type("leverantor_id", "int")], primary_key=["id"], rows=20)
    extra.foreign_keys.append(ForeignKey(["leverantor_id"], "leverantor", ["leverantor_id"], source="manual"))
    p.tables.append(extra)
    infer_table(extra, p)
    p.table("leverantor").columns.append(Column.from_type("saknas_i_db", "varchar(10)", custom=True))
    infer_table(p.table("leverantor"), p)
    for t in p.tables:
        t.rows = min(t.rows, 120)
    res = generate(p)
    check_integrity(p, res)
    with pytest.raises(RuntimeError):
        dbio.write_database(eng, res)
    written, warns = dbio.write_database(eng, res, create_missing=True)
    assert written == {"leverantor": 100, "faktura": 120, "extra": 20} and any("saknas_i_db" in w for w in warns)
    with eng.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM faktura o JOIN leverantor k ON k.leverantor_id = o.leverantor_id")).scalar() == 120
        assert conn.execute(sa.text("SELECT COUNT(*) FROM extra")).scalar() == 20
    with pytest.raises(Exception):  # samma nycklar igen -> allt rullas tillbaka
        dbio.write_database(eng, res)
    dbio.write_database(eng, res, empty_first=True)
    with eng.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM leverantor")).scalar() == 100

    care_res = generate(care, max_rows=40)
    assert len(export.write_csv(care_res, tmp_path / "csv")) == 9
    import pyarrow.parquet as pq
    paths = export.write_parquet(care_res, tmp_path / "pq")
    assert pq.read_table(paths[0]).num_rows == len(care_res.data[care_res.order[0]].rows)
    sql = export.write_sql(care_res, tmp_path / "d.sql", empty_first=True).read_text(encoding="utf-8-sig")
    assert "SET IDENTITY_INSERT [dbo].[Patient] ON;" in sql and "DELETE FROM [dbo].[Labbsvar];" in sql
    assert sql.index("INSERT INTO [dbo].[Patient]") < sql.index("INSERT INTO [dbo].[Vardkontakt]")

    yaml_path = tmp_path / "p.yaml"
    care.save(yaml_path)
    again = Project.load(yaml_path)
    assert generate(again, max_rows=40).data["dbo.Patient"].rows == care_res.data["dbo.Patient"].rows
