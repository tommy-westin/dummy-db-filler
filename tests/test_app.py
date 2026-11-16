"""Röktest av webbgränssnittet: varje sida ska gå att rita utan fel."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from dummyfiller.ddl import parse_ddl
from dummyfiller.inference import infer_project
from dummyfiller.model import Project

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "dummyfiller" / "app.py")
PAGES = ["1. Källa", "2. Diagram", "3. Tabeller och relationer", "4. Kolumner", "5. Värdelistor", "6. Generera"]


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
    at.session_state["page"] = PAGES[5]
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
    at.session_state["page"] = PAGES[3]
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
    project.dirty = {"tables": ["dbo.Leverantor"], "pct": 10, "kinds": ["whitespace", "duplicates"]}
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["project"] = project
    at.session_state["page"] = PAGES[3]
    at.session_state["cur_table"] = "dbo.DimLeverantor"
    at.session_state["cur_col"] = "Telefon"
    at.run()
    assert not at.exception
    assert any(c.label == "Generera flera versioner per rad" and c.value for c in at.checkbox)  # historik känns igen
    next(b for b in at.button if b.label == "Spara regel").click().run()
    assert not at.exception and rules.load_rules()[0]["pattern"] == "telefon"

    at.session_state["page"] = PAGES[4]
    at.run()
    assert not at.exception
    assert any("COUNT_BIG" in c.value for c in at.code)  # profilskriptet visas

    at.session_state["page"] = PAGES[5]
    at.run()
    next(s for s in at.selectbox if s.label.startswith("Scenario")).select("liten").run()
    next(b for b in at.button if b.label.startswith("Generera")).click().run()
    assert not at.exception
    res = at.session_state["result"]
    assert len(res.data["dbo.Leverantorsfaktura"].rows) == 20 and res.dirty_log
    assert any(m.label == "Föräldralösa rader" and m.value == "0" for m in at.metric)


def test_diagram_panels_and_events():
    """Diagramsteget: sidopanelen för tabell och kolumn, samt händelserna som diagrammet skickar."""
    project = _project()
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["project"] = project
    at.session_state["page"] = PAGES[1]
    at.run()
    assert not at.exception
    assert all(len(t.pos) == 2 for t in project.tables)  # automatisk placering
    assert any(s.value == "Så här gör du" for s in at.subheader)

    at.session_state["dg_sel"] = ("dbo.Patient", None)  # klick på tabellrubrik
    at.run()
    assert not at.exception and any(s.value == "Patient" for s in at.subheader)
    next(x for x in at.text_input if x.label == "Kolumnnamn").input("Hemkommun")
    next(b for b in at.button if b.label == "Lägg till kolumn").click().run()
    assert not at.exception
    col = project.table("dbo.Patient").column("Hemkommun")
    assert col is not None and col.generator == "address.municipality"
    assert at.session_state["dg_sel"] == ("dbo.Patient", "Hemkommun")
    assert any(s.value == "Patient.Hemkommun" for s in at.subheader)  # panelen följer med till den nya kolumnen

    next(s for s in at.selectbox if s.label == "Generator").select("Egna värden: Fast värde").run()
    assert not at.exception and col.generator == "constant" and col.manual

    at.session_state["diagram_cmp"] = {"type": "maximize", "on": True, "seq": "max-1"}  # ⛶ Maximera i diagrammet
    at.run()
    assert not at.exception and at.session_state["dg_max"] is True
    assert not any(h.value.startswith("2. Diagram") for h in at.header)  # rubriken döljs
    at.session_state["diagram_cmp"] = {"type": "maximize", "on": False, "seq": "max-2"}  # Esc
    at.run()
    assert not at.exception and at.session_state["dg_max"] is False
    assert any(h.value.startswith("2. Diagram") for h in at.header)

    at.session_state["dg_sel"] = ("dbo.Vardkontakt", "PatientID")  # klick på en relationspil
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "Ta bort relationen").click().run()
    assert not at.exception and project.table("dbo.Vardkontakt").fk_for("PatientID") is None


def test_edit_helpers():
    from dummyfiller import edit
    from dummyfiller.engine import generate

    p = _project()
    vk, pat = p.table("dbo.Vardkontakt"), p.table("dbo.Patient")
    fk = vk.fk_for("PatientID")
    vk.foreign_keys.remove(fk)
    # pilen dras "baklänges" från nyckeln: den vänds så att Patient blir förälder
    level, msg, new = edit.connect(p, "dbo.Patient", "PatientID", "dbo.Vardkontakt", "PatientID")
    assert level == "success" and new in vk.foreign_keys and new.ref_table == "dbo.Patient"
    assert edit.connect(p, "dbo.Vardkontakt", "Status", "dbo.Patient", "PatientID")[0] == "error"  # olika datatyp
    assert edit.connect(p, "dbo.Vardkontakt", "PatientID", "dbo.Vardenhet", "VardenhetID")[0] == "error"  # redan kopplad

    edit.rename_column(p, pat, "Fodelsedatum", "Fodd")
    edit.rename_column(p, vk, "Inskrivningsdatum", "Inskriven")
    edit.rename_table(p, pat, "Invanare", "dbo")
    assert new.ref_table == "dbo.Invanare" and p.table("dbo.Labbsvar").fk_for("PatientID").ref_table == "dbo.Invanare"
    assert "Inskriven +" in vk.column("Utskrivningsdatum").params["expr"]
    assert p.table("dbo.Labbsvar").column("Provtagningsdatum").params["column"] == "Inskriven"
    res = generate(p, max_rows=30)
    assert not res.warnings and "Fodd" in res.data["dbo.Invanare"].columns

    edit.delete_column(p, p.table("dbo.Diagnos"), "DiagnosKod")  # nyckeln som en annan tabell pekar på
    assert p.table("dbo.VardkontaktDiagnos").fk_for("DiagnosKod") is None
    for t in p.tables:
        t.pos = []
    edit.auto_layout(p)
    xs = {t.name: t.pos[0] for t in p.tables}
    assert xs["Vardenhet"] < xs["Invanare"] < xs["Vardkontakt"] < xs["Labbsvar"]


def test_autosave_survives_reload():
    """Ett projekt ska finnas kvar när sidan laddas om (ny session) och versioner ska gå att återställa."""
    from dummyfiller import store

    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = PAGES[1]
    at.run()
    assert not at.exception
    next(x for x in at.text_input if x.label == "Tabellnamn").input("Remiss")
    next(b for b in at.button if b.label == "Skapa tabell").click().run()
    assert not at.exception

    reloaded = AppTest.from_file(APP, default_timeout=60)  # som att ladda om sidan
    reloaded.run()
    assert not reloaded.exception
    assert [t.name for t in reloaded.session_state["project"].tables] == ["Remiss"]

    pid = reloaded.session_state["project_id"]
    vid = store.versions(pid)[-1]["id"]  # första versionen: tomt projekt
    reloaded.session_state["project"].tables[0].rows = 7
    reloaded.run()
    assert store.load(pid)[0].tables[0].rows == 7
    assert store.load_version(vid).tables == []

    next(b for b in reloaded.button if b.label == "➕ Nytt").click().run()
    assert not reloaded.exception and len(store.list_projects()) == 2
