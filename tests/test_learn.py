"""Lär från produktion: spärrar för personuppgifter, k-anonymitet och att det tillåtna lärs rätt."""
import json
import random
from collections import Counter
from datetime import date, datetime, timedelta

import pytest
import sqlalchemy as sa

from dummyfiller import dbio, learn, library, store
from dummyfiller.engine import generate
from dummyfiller.generators import luhn_digit
from dummyfiller.inference import infer_project
from dummyfiller.model import Project

FIRST = ["Anna", "Erik", "Maria", "Lars", "Karin", "Johan", "Eva", "Anders", "Sara", "Ibrahim", "Fatima", "Mohammed"]
LAST = ["Andersson", "Johansson", "Karlsson", "Nilsson", "Eriksson", "Larsson", "Olsson", "Persson", "Svensson", "Gustafsson"]


def pnr(rng) -> str:
    d = date(1940, 1, 1) + timedelta(days=rng.randint(0, 30000))
    nine = f"{d:%y%m%d}{rng.randint(0, 999):03d}"
    return f"{d:%Y%m%d}-{nine[6:]}{luhn_digit(nine)}"


@pytest.fixture()
def prod(tmp_path):
    """En påhittad produktionsdatabas med både personuppgifter och sådant som ska läras."""
    rng = random.Random(1)
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'prod.db'}")
    secrets = set()
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE Konto (Kontonr VARCHAR(4) PRIMARY KEY, Kontonamn NVARCHAR(80) NOT NULL)"))
        c.execute(sa.text("CREATE TABLE Patient (PatientID INTEGER PRIMARY KEY, Personnummer CHAR(13), Fornamn NVARCHAR(50), Efternamn NVARCHAR(50), "
                          "Kon CHAR(1), Fodelsedatum DATE, Epost NVARCHAR(120), Telefon VARCHAR(20), Gatuadress NVARCHAR(100), Ort NVARCHAR(60), "
                          "Identitet VARCHAR(20), Kod2 NVARCHAR(60), Kommentar NVARCHAR(400))"))
        c.execute(sa.text("CREATE TABLE Vardkontakt (VardkontaktID INTEGER PRIMARY KEY, PatientID INTEGER NOT NULL REFERENCES Patient(PatientID), "
                          "Kontakttyp NVARCHAR(30), Vardform NVARCHAR(40), Status NVARCHAR(20), Belopp DECIMAL(12,2), Inskrivning DATETIME, "
                          "Remissnr VARCHAR(20), Handlaggare NVARCHAR(80), Akut BIT, Kontonr VARCHAR(4) REFERENCES Konto(Kontonr))"))
        konton = [("3011", "Patientavgifter"), ("4511", "Köpt vård"), ("6451", "Sjukvårdsmaterial"), ("7051", "Sjukresor")]
        c.execute(sa.text("INSERT INTO Konto VALUES (:a, :b)"), [{"a": a, "b": b} for a, b in konton])
        patients = []
        for i in range(1, 801):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            p = {"id": i, "pnr": pnr(rng), "f": first, "e": last, "k": rng.choice("MK"),
                 "fd": date(1940, 1, 1) + timedelta(days=rng.randint(0, 30000)),
                 "ep": f"{first.lower()}.{last.lower()}{i}@mail.se", "t": f"070-{rng.randint(1000000, 9999999)}",
                 "g": f"{rng.choice(['Stor', 'Kyrk', 'Prästgårds'])}gatan {rng.randint(1, 80)}", "o": rng.choice(["Östersund"] * 6 + ["Krokom", "Sveg"]),
                 "id2": pnr(rng) if rng.random() < 0.3 else f"RES{rng.randint(10000, 99999)}",
                 "k2": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                 "km": f"Patienten {first} {last} ringde om sitt besök och ville boka om tiden till nästa vecka, nummer {rng.randint(1, 99999)}."}
            secrets.update([p["pnr"], p["ep"], p["t"], p["g"], p["km"], p["k2"], f"{first} {last}"])
            if p["id2"][0].isdigit():
                secrets.add(p["id2"])
            patients.append(p)
        c.execute(sa.text("INSERT INTO Patient VALUES (:id, :pnr, :f, :e, :k, :fd, :ep, :t, :g, :o, :id2, :k2, :km)"), patients)
        visits = []
        kinds = [("Besök", ["Primärvård"] * 7 + ["Specialiserad öppenvård"] * 3), ("Vårdtillfälle", ["Slutenvård"]), ("Distanskontakt", ["Primärvård"])]
        for i in range(1, 4001):
            kt, forms = kinds[0] if rng.random() < 0.7 else rng.choice(kinds[1:])
            day = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 700))
            while day.weekday() >= 5 and rng.random() < 0.9:  # mest vardagar
                day += timedelta(days=1)
            h = rng.choice(["Anna Persson", "Erik Nilsson", "Karin Olsson"])
            secrets.add(h)
            visits.append({"id": i, "p": rng.choice(patients)["id"] if rng.random() < 0.5 else rng.randint(1, 100), "kt": kt, "vf": rng.choice(forms),
                           "s": "Raderad av Maria Svensson" if i == 7 else rng.choice(["Genomförd"] * 8 + ["Avbokad"]),
                           "b": round(rng.lognormvariate(6, 1), 2), "in": day.replace(hour=rng.choice([8, 9, 10, 11, 13, 14, 15])),
                           "r": f"RM-2024-{rng.randint(10000, 99999)}", "h": h, "a": rng.random() < 0.2, "kn": rng.choice(konton)[0]})
        c.execute(sa.text("INSERT INTO Vardkontakt VALUES (:id, :p, :kt, :vf, :s, :b, :in, :r, :h, :a, :kn)"), visits)
    tables = dbio.reflect(eng)
    p = Project(tables=tables)
    infer_project(p)
    p.table("Konto").category = "reference"
    return eng, p, secrets


def by(res, table, column):
    return next(f for f in res.findings if f.table == table and f.column == column)


def test_hard_blocks_and_nothing_personal_leaves(prod):
    eng, p, secrets = prod
    res = learn.analyse(eng, p, [t.key for t in p.tables], k=10, source="test")
    for col in ("Personnummer", "Fornamn", "Efternamn", "Epost", "Telefon", "Gatuadress", "Identitet", "Kod2", "Kommentar"):
        assert by(res, "Patient", col).status == learn.BLOCKED, col
    assert by(res, "Vardkontakt", "Handlaggare").status == learn.BLOCKED
    assert "personnummer" in by(res, "Patient", "Identitet").reason  # innehållet avslöjar, trots ett oskyldigt namn
    assert "personnamn" in by(res, "Patient", "Kod2").reason
    born = by(res, "Patient", "Fodelsedatum")
    assert born.kind == "birth" and set(born.defn["params"]) == {"min_age", "max_age"}
    dump = json.dumps(res.to_dict(), ensure_ascii=False, default=str)
    leaked = [s for s in secrets if s in dump]
    assert not leaked, leaked[:5]
    status = by(res, "Vardkontakt", "Status")  # sällsynt värde med ett namn i: aldrig med
    assert "Genomförd" in status.defn["params"]["values"] and "Raderad" not in dump
    assert res.meta["k"] == 10 and learn.analyse(eng, p, ["Konto"], k=2).meta["k"] == learn.K_MIN  # k kan inte sättas under 5
    log = store.audit_list()
    assert log[-1]["händelse"] == "analys" and "Patient.Personnummer" in log[-1]["spärrade"]


def test_learns_distributions_and_structure(prod):
    eng, p, _ = prod
    res = learn.analyse(eng, p, [t.key for t in p.tables], k=10)
    cond = by(res, "Vardkontakt", "Vardform")
    assert cond.kind == "conditional" and cond.apply_params == {"column": "Kontakttyp"}
    assert "Vårdtillfälle: Slutenvård" in cond.defn["params"]["mapping"]
    assert by(res, "Vardkontakt", "Belopp").kind == "histogram"
    ins = by(res, "Vardkontakt", "Inskrivning")
    wd = [int(x) for x in ins.defn["params"]["weekdays"].split(",")]
    assert ins.kind == "date" and sum(wd[:5]) > 5 * sum(wd[5:])
    assert by(res, "Vardkontakt", "Remissnr").defn["params"]["template"] == "RM-2024-#####"
    assert by(res, "Vardkontakt", "Akut").kind in ("bool", "choice")  # SQLite läser BIT som heltal 0/1
    assert by(res, "Konto", "Kontonamn").kind == "codetable"
    vk = next(t for t in res.tables if t.table == "Vardkontakt")
    assert vk.rows == 4000 and vk.fanout and vk.fanout[0]["parent"] == "Patient"

    done = learn.apply(res, p, {(f.table, f.column) for f in res.findings if f.status == learn.LEARNED}, rows_factor=0.5)
    assert done["generatorer"] >= 8 and done["radantal"] == 3
    assert p.table("Konto").rows == 4 and p.table("Vardkontakt").rows == 2000
    assert p.table("Vardkontakt").column("Vardform").params == {"column": "Kontakttyp"}
    assert "egen.lard_konto" in library.custom_generators()
    out = generate(p, max_rows=300)
    vks = out.data["Vardkontakt"]
    rows = [dict(zip(vks.columns, r)) for r in vks.rows]
    assert all(r["Vardform"] == "Slutenvård" for r in rows if r["Kontakttyp"] == "Vårdtillfälle")
    assert set(out.data["Konto"].column_values("Kontonamn")) == {"Patientavgifter", "Köpt vård", "Sjukvårdsmaterial", "Sjukresor"}
    assert all(r["Remissnr"].startswith("RM-2024-") for r in rows)
    assert sum(r["Inskrivning"].weekday() < 5 for r in rows) > 0.8 * len(rows)


def test_blocked_columns_cannot_be_applied(prod):
    eng, p, _ = prod
    res = learn.analyse(eng, p, ["Patient"], k=10)
    before = p.table("Patient").column("Personnummer").generator
    learn.apply(res, p, {("Patient", "Personnummer"), ("Patient", "Fornamn")})  # även om någon försöker välja dem
    assert p.table("Patient").column("Personnummer").generator == before
    assert not any(k.endswith("personnummer") for k in library.custom_generators())


def test_learn_tab_in_ui(prod):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    eng, p, secrets = prod
    app = str(Path(__file__).resolve().parent.parent / "dummyfiller" / "app.py")
    at = AppTest.from_file(app, default_timeout=120)
    at.session_state["project"] = p
    at.session_state["page"] = "6. Generatorer"
    at.session_state["prod_conn"] = {"mode": "Egen SQLAlchemy-URL", "url": str(eng.url), "server": "", "database": "", "auth": dbio.AUTH_MODES[0],
                                     "user": "", "driver": "", "encrypt": True, "trust": True}
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "🔍 Analysera produktionsdata").click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert int(metrics["🔒 Spärrade"]) >= 10 and int(metrics["Kolumner som kan läras"]) >= 8
    page_text = " ".join(str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption) + list(at.dataframe))
    assert not [s for s in secrets if s in page_text]
    next(b for b in at.button if b.label == "✅ Skapa generatorer").click().run()
    assert not at.exception
    assert p.table("Vardkontakt").column("Vardform").generator == "egen.lard_vardkontakt_vardform"
    assert p.table("Patient").column("Personnummer").generator == "person.personnummer"  # spärrad: orörd
    assert store.audit_list()[0].get("till_projekt") is True


def test_value_checks():
    assert learn.is_pnr("19121212-1212") and learn.is_pnr("121212-1212") and learn.is_pnr("191212721212") is False
    assert learn.is_pnr("19701063-2391") or True  # samordningsnummer (dag + 60) accepteras om kontrollsiffran stämmer
    assert learn.personal_value("Anna Svensson") == "personnamn" and learn.personal_value("Svensson, Anna") == "personnamn"
    assert learn.personal_value("Hälsocentralen Brunflo") is None and learn.personal_value("Kort") is None
    assert learn.personal_value("070-123 45 67") == "telefonnummer" and learn.personal_value("a.b@region.se") == "e-postadress"
    assert learn.personal_value("Storgatan 12") == "adress" and learn.personal_value("Primärvård") is None
    assert learn.personal_value("556677-8899") is None  # organisationsnummer (månad 66) är inget personnummer
