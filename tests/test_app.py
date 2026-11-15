"""Röktest av webbgränssnittet: varje sida ska gå att rita utan fel."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from dummyfiller.ddl import parse_ddl
from dummyfiller.inference import infer_project
from dummyfiller.model import Project

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "dummyfiller" / "app.py")
PAGES = ["1. Källa", "2. Tabeller och relationer", "3. Kolumner", "4. Värdelistor", "5. Generera"]


def _project() -> Project:
    tables, _ = parse_ddl((ROOT / "exempel" / "vard.sql").read_text(encoding="utf-8"))
    p = Project(tables=tables, value_lists={"orter": ["Lund", "Umeå"]})
    infer_project(p)
    for t in p.tables:
        t.rows = min(t.rows, 50)
    return p


def test_pages_render_empty_and_loaded():
    for project in (Project(), _project()):
        for page in PAGES:
            at = AppTest.from_file(APP, default_timeout=60)
            at.session_state["project"] = project
            at.session_state["page"] = page
            at.run()
            assert not at.exception, f"{page}: {at.exception}"


def test_generate_flow():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["project"] = _project()
    at.session_state["page"] = PAGES[4]
    at.run()
    next(b for b in at.button if b.label.startswith("Generera")).click().run()
    assert not at.exception
    assert at.session_state["result"] is not None
    assert any("rader genererade" in s.value for s in at.success)


def test_load_example_and_change_generator():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    next(b for b in at.button if b.label.startswith("Läs in exempelschema")).click().run()
    assert not at.exception
    assert len(at.session_state["project"].tables) == 9
    at.session_state["page"] = PAGES[2]
    at.session_state["cur_table"] = "dbo.Patient"
    at.session_state["cur_col"] = "Telefon"
    at.run()
    assert not at.exception
    gen = next(s for s in at.selectbox if s.label == "Generator")
    gen.select("Egna värden: Fast värde").run()
    assert not at.exception
    col = at.session_state["project"].table("dbo.Patient").column("Telefon")
    assert col.generator == "constant" and col.manual


def test_new_features_in_ui():
    from dummyfiller import rules
    from tests.test_features import sales

    project = sales()
    project.dirty = {"tables": ["dbo.Kund"], "pct": 10, "kinds": ["whitespace", "duplicates"]}
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["project"] = project
    at.session_state["page"] = PAGES[2]
    at.session_state["cur_table"] = "dbo.DimKund"
    at.session_state["cur_col"] = "Telefon"
    at.run()
    assert not at.exception
    assert any(c.label == "Generera flera versioner per rad" and c.value for c in at.checkbox)  # historik känns igen
    next(b for b in at.button if b.label == "Spara regel").click().run()
    assert not at.exception and rules.load_rules()[0]["pattern"] == "telefon"

    at.session_state["page"] = PAGES[3]
    at.run()
    assert not at.exception
    assert any("COUNT_BIG" in c.value for c in at.code)  # profilskriptet visas

    at.session_state["page"] = PAGES[4]
    at.run()
    next(s for s in at.selectbox if s.label.startswith("Scenario")).select("liten").run()
    next(b for b in at.button if b.label.startswith("Generera")).click().run()
    assert not at.exception
    res = at.session_state["result"]
    assert len(res.data["dbo.KundOrder"].rows) == 20 and res.dirty_log
    assert any(m.label == "Föräldralösa rader" and m.value == "0" for m in at.metric)
