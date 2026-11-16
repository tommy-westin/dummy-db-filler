"""Matchning av projektet mot en produktion där tabeller och kolumner heter annorlunda."""
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from dummyfiller import dbio, learn, matching
from dummyfiller.ddl import parse_ddl
from dummyfiller.inference import infer_project
from dummyfiller.model import Project
from tests.test_learn import FIRST, LAST, pnr

PROJECT_DDL = """
CREATE TABLE Patient (PatientID int NOT NULL PRIMARY KEY, Personnummer char(13), Fornamn nvarchar(50), Efternamn nvarchar(50),
    Kon char(1), Fodelsedatum date, Kod1 varchar(10));
CREATE TABLE Vardkontakt (VardkontaktID int NOT NULL PRIMARY KEY, PatientID int NOT NULL REFERENCES Patient(PatientID),
    Kontakttyp nvarchar(30), Belopp decimal(12,2), Inskrivning datetime2);
"""


@pytest.fixture()
def prod(tmp_path):
    rng = random.Random(3)
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'prod.db'}")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE tblPatient (PatientId INTEGER PRIMARY KEY, PNR CHAR(13), FirstName TEXT, LastName TEXT, Gender CHAR(1), "
                          "BirthDate DATE, Handlaggare_kod VARCHAR(10))"))
        c.execute(sa.text("CREATE TABLE Encounters (EncounterId INTEGER PRIMARY KEY, PatientRef INTEGER, EncounterType TEXT, Amount TEXT, "
                          "AdmissionDate DATETIME)"))
        c.execute(sa.text("CREATE TABLE AuditLog (LogId INTEGER PRIMARY KEY, Message TEXT)"))
        c.execute(sa.text("INSERT INTO tblPatient VALUES (:i, :p, :f, :l, :g, :b, :h)"),
                  [{"i": i, "p": pnr(rng), "f": rng.choice(FIRST), "l": rng.choice(LAST), "g": rng.choice("MK"),
                    "b": date(1950, 1, 1) + timedelta(days=rng.randint(0, 25000)), "h": rng.choice(["AP01", "EN02", "KO03"])} for i in range(1, 401)])
        c.execute(sa.text("INSERT INTO Encounters VALUES (:i, :p, :t, :a, :d)"),
                  [{"i": i, "p": rng.randint(1, 400), "t": rng.choice(["Besök"] * 7 + ["Vårdtillfälle"] * 3),
                    "a": f"{rng.lognormvariate(5, 0.8):.2f}", "d": datetime(2025, 1, 1) + timedelta(hours=rng.randint(0, 9000))} for i in range(1, 2001)])
    tables, _ = parse_ddl(PROJECT_DDL, default_schema="")
    p = Project(tables=tables)
    infer_project(p)
    return eng, p


def test_auto_and_manual_matching(prod):
    eng, p = prod
    schema = dbio.list_tables(eng)
    assert {t["name"] for t in schema} == {"tblPatient", "Encounters", "AuditLog"}
    m = matching.auto_match(p, schema)
    assert m["tables"]["Patient"]["name"] == "tblPatient"  # prefixet tbl tas bort
    cols = {k: v["name"] for k, v in m["columns"]["Patient"].items()}
    assert cols == {"PatientID": "PatientId", "Personnummer": "PNR", "Fornamn": "FirstName", "Efternamn": "LastName", "Kon": "Gender",
                    "Fodelsedatum": "BirthDate"}  # synonymer; Kod1 har ingen motsvarighet
    assert "Vardkontakt" not in m["tables"]  # för olika namn för att matchas automatiskt

    matching.link_table(p, m, schema, "Vardkontakt", "Encounters")  # manuellt
    vc = {k: v["name"] for k, v in m["columns"]["Vardkontakt"].items()}
    assert vc["VardkontaktID"] == "EncounterId" and vc["Kontakttyp"] == "EncounterType" and vc["Belopp"] == "Amount"
    assert vc["Inskrivning"] == "AdmissionDate" and "PatientID" not in vc
    matching.link_column(m, "Vardkontakt", "PatientID", "PatientRef")
    matching.link_column(m, "Patient", "Kod1", "Handlaggare_kod")
    assert m["columns"]["Vardkontakt"]["PatientID"]["kind"] == matching.MANUAL
    assert matching.type_mismatch(p.table("Vardkontakt").column("Belopp"), "string")

    again = matching.auto_match(p, schema, m)  # manuella kopplingar överlever en ny automatisk matchning
    assert again["tables"]["Vardkontakt"]["name"] == "Encounters" and again["columns"]["Vardkontakt"]["PatientID"]["name"] == "PatientRef"
    assert matching.auto_match(p, schema, m, reset=True)["tables"].get("Vardkontakt") is None

    res = learn.analyse(eng, p, ["Patient", "Vardkontakt"], k=10, mapping=m)
    f = {(x.table, x.column): x for x in res.findings}
    assert f[("Patient", "Kod1")].status == learn.BLOCKED and "Handlaggare_kod" in f[("Patient", "Kod1")].reason  # produktionens namn avslöjar
    assert f[("Patient", "Personnummer")].status == learn.BLOCKED and f[("Patient", "Fornamn")].status == learn.BLOCKED
    assert f[("Patient", "Kon")].kind == "choice" and f[("Vardkontakt", "Kontakttyp")].kind == "choice"
    assert f[("Vardkontakt", "Belopp")].kind == "histogram"  # text i produktionen tolkas som projektets decimaltal
    vk = next(t for t in res.tables if t.table == "Vardkontakt")
    assert vk.rows == 2000 and vk.fanout and vk.fanout[0]["parent"] == "Patient"

    m["tables"].pop("Patient")
    res = learn.analyse(eng, p, ["Patient"], k=10, mapping=m)
    assert "inte matchad" in res.tables[0].error


def test_matching_in_ui(prod):
    from streamlit.testing.v1 import AppTest
    eng, p = prod
    app = str(Path(__file__).resolve().parent.parent / "dummyfiller" / "app.py")
    at = AppTest.from_file(app, default_timeout=120)
    at.session_state["project"] = p
    at.session_state["section"], at.session_state["lib_page"] = "📚 Domänbibliotek", "Lär från produktion"
    at.session_state["prod_conn"] = {"mode": "Egen SQLAlchemy-URL", "url": str(eng.url), "server": "", "database": "", "auth": dbio.AUTH_MODES[0],
                                     "user": "", "driver": "", "encrypt": True, "trust": True}
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "🔗 Hämta produktionens schema").click().run()
    assert not at.exception and p.prod_mapping["tables"]["Patient"]["name"] == "tblPatient"
    at.session_state["map_tables_cmp"] = {"type": "link", "l": "Vardkontakt", "r": "Encounters", "seq": "t1"}  # dra en linje
    at.run()
    assert not at.exception and p.prod_mapping["tables"]["Vardkontakt"]["kind"] == matching.MANUAL
    assert at.session_state["map_sel"] == "Vardkontakt"
    at.session_state["map_cols_cmp"] = {"type": "link", "l": "PatientID", "r": "PatientRef", "seq": "c1"}
    at.run()
    assert not at.exception and p.prod_mapping["columns"]["Vardkontakt"]["PatientID"]["name"] == "PatientRef"
    at.session_state["map_cols_cmp"] = {"type": "unlink", "l": "Belopp", "seq": "c2"}  # klicka på linjen
    at.run()
    assert "Belopp" not in p.prod_mapping["columns"]["Vardkontakt"]
    next(b for b in at.button if b.label == "🔍 Analysera produktionsdata").click().run()
    assert not at.exception
    res = at.session_state["learn_result"]
    skipped = {(f.table, f.column): f for f in res.findings}
    assert skipped[("Vardkontakt", "Belopp")].reason == "saknar motsvarighet i produktionen"
    assert skipped[("Vardkontakt", "Kontakttyp")].status == learn.LEARNED
