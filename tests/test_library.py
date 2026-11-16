"""Generatorbiblioteket: egna generatorer, ändrade inbyggda listor, projektkopior och delning."""
from collections import Counter

import pytest

from dummyfiller import library, region, rules, store
from dummyfiller.engine import generate
from dummyfiller.generators import REGISTRY
from dummyfiller.inference import infer_project, infer_table
from dummyfiller.model import Column, ForeignKey, Project, Table

ANSVAR = {"key": "egen.jh_ansvar", "name": "JH: Ansvar", "kind": "table", "description": "Ansvarskoder",
          "columns": ["Kod", "Benämning", "Förvaltning", "Vikt"], "weight": "Vikt",
          "rows": [["11000", "Ekonomienheten", "Regionstaben", 1], ["22000", "Hälsocentralen Brunflo", "HSF", 3],
                   ["33000", "Folktandvården Sveg", "FTV", 0], ["", "", "", ""]]}
FAKNR = {"key": "egen.jh_fakturanummer", "name": "JH: Fakturanummer", "kind": "preset", "base": "pattern",
         "params": {"template": "JH-{seq:05}"}}


def project_with(columns, category="transaction", rows=60):
    t = Table("Rad", columns=[Column.from_type("RadID", "int", nullable=False)] + columns, primary_key=["RadID"], rows=rows, category=category,
              category_manual=True)
    p = Project(tables=[t])
    infer_project(p, set_rows=False)
    return p, t


def use(t, name, key, **params):
    c = t.column(name)
    c.generator, c.params, c.manual = key, params, True


def test_table_generator_keeps_rows_together():
    library.save_generator(ANSVAR)
    assert REGISTRY["egen.jh_ansvar"].group == "Egna" and library.size_of("egen.jh_ansvar") == 3
    p, t = project_with([Column.from_type("Ansvar", "varchar(5)"), Column.from_type("Namn", "nvarchar(60)"), Column.from_type("Forv", "nvarchar(20)")])
    use(t, "Ansvar", "egen.jh_ansvar", field="Kod")
    use(t, "Namn", "egen.jh_ansvar", field="Benämning")
    use(t, "Forv", "egen.jh_ansvar", field="Förvaltning")
    res = generate(p)
    rows = res.data["dbo.Rad"].rows
    pairs = Counter((r[1], r[2], r[3]) for r in rows)
    assert set(pairs) <= {("11000", "Ekonomienheten", "Regionstaben"), ("22000", "Hälsocentralen Brunflo", "HSF")}  # vikt 0 aldrig
    assert pairs[("22000", "Hälsocentralen Brunflo", "HSF")] > pairs[("11000", "Ekonomienheten", "Regionstaben")]
    # i en kodtabell: en rad per tabellrad i ordning, och radantalet följer tabellen
    q, k = project_with([Column.from_type("Kod", "varchar(5)")], category="reference")
    use(k, "Kod", "egen.jh_ansvar", field="Kod")
    infer_table(k, q, set_rows=True)
    assert k.rows == 3 and generate(q).data["dbo.Rad"].column_values("Kod") == ["11000", "22000", "33000"]


def test_preset_follows_library_changes_and_guides_fk():
    library.save_generator(FAKNR)
    p, t = project_with([Column.from_type("Fakturanr", "varchar(12)")])
    use(t, "Fakturanr", "egen.jh_fakturanummer")
    assert generate(p).data["dbo.Rad"].column_values("Fakturanr")[:2] == ["JH-00001", "JH-00002"]
    library.save_generator({**FAKNR, "params": {"template": "LF{seq:07}"}})  # ändras i biblioteket: alla kolumner följer med
    assert generate(p).data["dbo.Rad"].column_values("Fakturanr")[0] == "LF0000001"

    library.save_generator(ANSVAR)  # styrd relation: barnets kod väljer förälderraden
    kod = Table("Ansvar", columns=[Column.from_type("Kod", "varchar(5)", nullable=False), Column.from_type("Namn", "nvarchar(60)")],
                primary_key=["Kod"], category="reference", category_manual=True)
    rad = Table("Bokning", columns=[Column.from_type("BokningID", "int", nullable=False), Column.from_type("Ansvar", "varchar(5)", nullable=False),
                                    Column.from_type("Namn", "nvarchar(60)")], primary_key=["BokningID"], rows=200, category="transaction", category_manual=True)
    rad.foreign_keys.append(ForeignKey(["Ansvar"], "dbo.Ansvar", ["Kod"], guided=True))
    q = Project(tables=[kod, rad])
    infer_project(q, set_rows=False)
    for t2 in (kod, rad):
        use(t2, t2.columns[0 if t2 is kod else 1].name, "egen.jh_ansvar", field="Kod")
        use(t2, "Namn", "egen.jh_ansvar", field="Benämning")
    kod.rows = 3
    res = generate(q)
    names = dict(zip(res.data["dbo.Ansvar"].column_values("Kod"), res.data["dbo.Ansvar"].column_values("Namn")))
    for a, n in zip(res.data["dbo.Bokning"].column_values("Ansvar"), res.data["dbo.Bokning"].column_values("Namn")):
        assert names[a] == n and a != "33000"


def test_builtin_list_override_and_reset():
    original = list(region.ACCOUNTS)
    rows = [["4011", "Köpt vård från annan region", 1000, 2000, 1], ["6999", "Övrigt", 10, 20, 1]]
    library.save_list("region.accounts", rows)
    assert library.is_overridden("region.accounts") and len(region.ACCOUNTS) == 2
    p, t = project_with([Column.from_type("Kontonr", "varchar(4)"), Column.from_type("Kontonamn", "nvarchar(60)"), Column.from_type("Belopp", "decimal(12,2)")])
    res = generate(p)
    accounts = set(res.data["dbo.Rad"].column_values("Kontonr"))
    assert accounts == {"4011", "6999"}
    assert all(1000 <= b <= 2000 for a, b in zip(res.data["dbo.Rad"].column_values("Kontonr"), res.data["dbo.Rad"].column_values("Belopp")) if a == "4011")
    with pytest.raises(ValueError):
        library.save_list("region.accounts", [["4011", "Fel", "inte ett tal", 2, 1]])
    library.reset_list("region.accounts")
    assert region.ACCOUNTS == original and not library.is_overridden("region.accounts")

    library.save_list("preset.hr_absence", [["Semester", 5], ["Sjuk", 1]])  # förvalda värdelistor styr nya tolkningar
    p, t = project_with([Column.from_type("Franvaroorsak", "nvarchar(30)")])
    assert set(generate(p).data["dbo.Rad"].column_values("Franvaroorsak")) == {"Semester", "Sjuk"}


def test_project_copy_keeps_working_without_library(tmp_path, monkeypatch):
    library.save_generator(FAKNR)
    p, t = project_with([Column.from_type("Fakturanr", "varchar(12)")])
    use(t, "Fakturanr", "egen.jh_fakturanummer")
    library.snapshot_into(p)
    assert list(p.custom_generators) == ["egen.jh_fakturanummer"]
    path = tmp_path / "p.yaml"
    p.save(path)
    monkeypatch.setenv("DUMMYFILLER_DB", str(tmp_path / "kollega.db"))  # en kollega utan generatorn i sitt bibliotek
    library.refresh(force=True)
    assert "egen.jh_fakturanummer" not in REGISTRY
    q = Project.load(path)
    assert generate(q).data["dbo.Rad"].column_values("Fakturanr")[0] == "JH-00001"
    assert "saknas" in library.origin("egen.jh_fakturanummer")


def test_shared_folder_publish_and_sync(tmp_path, monkeypatch):
    import os
    library.save_generator(FAKNR)
    library.save_codebook("diagnosis", [["X01.1", "Testdiagnos"]])
    library.save_test_pnr(["19121212-1212"])
    path = library.publish()
    assert path.parent == library.shared_dir() and path.exists()
    assert library.sync_shared() == []  # den egna publiceringen läses inte in igen

    monkeypatch.setenv("DUMMYFILLER_DB", str(tmp_path / "kollega.db"))  # en kollega med tom databas och samma fil i mappen
    library.refresh(force=True)
    assert "egen.jh_fakturanummer" not in REGISTRY and library.codebook("diagnosis") is None
    done = library.sync_shared()
    assert done[0][0] == library.SHARED_FILE and done[0][1]["generatorer"] == 1 and done[0][1]["kodverk"] == 1
    assert library.codebook("diagnosis") == [["X01.1", "Testdiagnos"]] and library.test_pnr() == ["19121212-1212"]
    assert library.sync_shared() == []  # oförändrad fil läses inte in igen

    p, t = project_with([Column.from_type("Fakturanr", "varchar(12)"), Column.from_type("Diagnoskod", "varchar(8)")])
    use(t, "Fakturanr", "egen.jh_fakturanummer")
    t.category = "reference"
    use(t, "Diagnoskod", "care.diagnosis_code")
    infer_table(t, p, set_rows=True)
    assert "X01.1" in generate(p).data["dbo.Rad"].column_values("Diagnoskod")  # kodverket i biblioteket gäller alla projekt

    path.write_text(path.read_text(encoding="utf-8").replace("JH-{seq:05}", "NY-{seq:05}"), encoding="utf-8")  # teamet uppdaterar
    os.utime(path, None)
    assert library.sync_shared() and generate(p).data["dbo.Rad"].column_values("Fakturanr")[0] == "NY-00001"


def test_export_import_and_cli(tmp_path, monkeypatch, capsys):
    library.save_generator(ANSVAR)
    library.save_list("region.activities", [["100", "Primärvård", 1]])
    rules.add_rule("*ansvar", "egen.jh_ansvar", {"field": "Kod"}, "string")
    text = library.export_yaml()
    monkeypatch.setenv("DUMMYFILLER_DB", str(tmp_path / "ny.db"))
    monkeypatch.setenv("DUMMYFILLER_RULES", str(tmp_path / "nya_regler.yaml"))
    rules._cache = None
    library.refresh(force=True)
    assert "egen.jh_ansvar" not in REGISTRY and len(region.ACTIVITIES) == 10
    assert library.import_yaml(text) == {"generatorer": 1, "listor": 1, "regler": 1}
    assert "egen.jh_ansvar" in REGISTRY and region.ACTIVITIES == [("100", "Primärvård", 1)]
    p, t = project_with([Column.from_type("Ansvar", "varchar(5)")])  # regeln använder den egna generatorn
    assert t.column("Ansvar").generator == "egen.jh_ansvar"

    # kommandoraden: --bibliotek lägger på ett bibliotek från fil utan att spara det
    monkeypatch.setenv("DUMMYFILLER_DB", str(tmp_path / "cli.db"))
    library.refresh(force=True)
    lib = tmp_path / "bibliotek.yaml"
    lib.write_text(text, encoding="utf-8")
    use(t, "Ansvar", "egen.jh_ansvar", field="Benämning")
    p.custom_generators = {}
    proj = tmp_path / "p.yaml"
    p.save(proj)
    from dummyfiller.__main__ import main
    assert main(["generate", str(proj), "--target", "csv", "--out", str(tmp_path / "csv"), "--bibliotek", str(lib)]) == 0
    assert "1;Hälso" in (tmp_path / "csv" / "dbo.Rad.csv").read_text(encoding="utf-8-sig")  # varchar(5): benämningen kortas
    assert store.lib_items() == []
