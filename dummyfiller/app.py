"""Webbgränssnittet (Streamlit). Startas med:  python -m dummyfiller"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # så att paketet hittas även utan installation
    sys.path.insert(0, str(ROOT))

import copy  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from datetime import date, timedelta  # noqa: E402

from dummyfiller import care, dbio, edit, export, learn, library, matching, prodprofile, quality, rules, store, valuelists  # noqa: E402
from dummyfiller.ddl import parse_ddl  # noqa: E402
from dummyfiller.dirty import KINDS as DIRTY_KINDS  # noqa: E402
from dummyfiller.engine import estimated_rows, generate, load_order  # noqa: E402
from dummyfiller.generators import LABEL_TO_KEY, LIST_MODES, REGISTRY, defaults, label_of  # noqa: E402
from dummyfiller.inference import (default_fk_settings, default_rows, infer_column, infer_table, norm,  # noqa: E402
                                   suggest_relations)
from dummyfiller.model import CATEGORIES, DISTRIBUTIONS, Column, ForeignKey, Project, Table, merge_tables, parse_type  # noqa: E402

st.set_page_config(page_title="Dummyfiller", page_icon="🧪", layout="wide")
ss = st.session_state
PAGES = ["1. Källa", "2. Diagram", "3. Tabeller och relationer", "4. Kolumner", "5. Värdelistor", "6. Generatorer", "7. Generera"]
CAT_LABELS = list(CATEGORIES.values())
CAT_BY_LABEL = {v: k for k, v in CATEGORIES.items()}
DIST_LABELS = list(DISTRIBUTIONS.values())
DIST_BY_LABEL = {v: k for k, v in DISTRIBUTIONS.items()}
GEN_LABELS = [label_of(k) for k in REGISTRY]
COMPUTED_LABEL = "(sätts av databasen)"

ss.setdefault("ver", 0)
ss.setdefault("result", None)
ss.setdefault("flash", [])
ss.setdefault("conn", {"mode": "SQL Server", "server": "localhost", "database": "", "auth": dbio.AUTH_MODES[0], "user": "",
                       "driver": "", "encrypt": True, "trust": True, "url": "", "schemas": ""})
ss.setdefault("pw", "")


def use_project(p: Project, pid: int, digest: str):
    """Gör projektet till det aktiva i den här fliken."""
    ss.project, ss.project_id, ss.project_hash = p, pid, digest
    ss.result = None
    ss.dg_sel = (None, None)
    if p.connection:
        ss.conn.update(p.connection)


def import_project(p: Project, note: str):
    """Läser in ett projekt från fil. Finns ett projekt med samma namn uppdateras det; det gamla innehållet finns kvar i historiken."""
    match = next((x for x in store.list_projects() if x["name"] == p.name), None)
    if match:
        store.save(match["id"], ss.project if ss.get("project_id") == match["id"] else store.load(match["id"])[0], None, "Före inläsning från fil")
        use_project(p, match["id"], store.save(match["id"], p, None, note))
    else:
        use_project(p, *store.create(p, note))


def open_last_project():
    """Öppnar det senast använda projektet i den lokala databasen, eller skapar ett nytt om det inte finns något."""
    pid = store.last_project_id()
    loaded = store.load(pid) if pid else None
    if loaded:
        use_project(loaded[0], pid, loaded[1])
    else:
        use_project(Project(), *store.create(Project()))


# projektet hämtas från den lokala databasen, så att arbetet finns kvar när sidan laddas om
if "project" not in ss and (ss.get("_linked") or not st.query_params.get("projekt")):
    open_last_project()
elif "project" in ss and "project_id" not in ss:  # projekt som lagts i sessionen utifrån (t.ex. i tester)
    ss.project_id, ss.project_hash = store.create(ss.project)
if not ss.get("_linked"):  # direktlänk: http://localhost:8501/?projekt=projekt/vard.yaml&steg=2
    ss["_linked"] = True
    qp = st.query_params
    if qp.get("projekt"):
        try:
            import_project(Project.load(qp["projekt"]), f"Inläst från {qp['projekt']}")
            ss.project_path = qp["projekt"]
        except Exception as e:
            ss.flash.append(("error", f"Kunde inte öppna {qp['projekt']}: {e}"))
        del st.query_params["projekt"]  # annars skulle en omladdning läsa in filen igen ovanpå ändringarna
    if qp.get("steg", "").isdigit() and 1 <= int(qp["steg"]) <= len(PAGES):
        ss.page = PAGES[int(qp["steg"]) - 1]
if "project" not in ss:  # länken gick inte att öppna
    open_last_project()
project: Project = ss.project
library.refresh(project)
GEN_LABELS = [label_of(k) for k in REGISTRY if not k.startswith(library.PREFIX + "__")]


# ---------------------------------------------------------------- hjälpfunktioner

def flash(kind: str, text: str):
    ss.flash.append((kind, text))


def changed():
    """Modellen har ändrats: bygg om redigerbara tabeller och släng gammal genererad data."""
    ss.ver += 1
    ss.result = None


def pick(label: str, options: list[str], state_key: str) -> str:
    """Selectbox vars val överlever sidbyten och kan sättas från koden med select()."""
    cur = ss.get(state_key)
    val = st.selectbox(label, options, index=options.index(cur) if cur in options else 0,
                       key=f"pick_{state_key}_{ss.get('pickver_' + state_key, 0)}")
    ss[state_key] = val
    return val


def select(state_key: str, value: str):
    ss[state_key] = value
    ss["pickver_" + state_key] = ss.get("pickver_" + state_key, 0) + 1


def take_edits(name: str) -> dict:
    return dict((ss.get(f"{name}_{ss.ver}") or {}).get("edited_rows") or {})


def editor(name: str, df: pd.DataFrame, **kw):
    return st.data_editor(df, key=f"{name}_{ss.ver}", hide_index=True, width="stretch", **kw)


def to_df(data, limit: int = 200) -> pd.DataFrame:
    rows = [[float(v) if isinstance(v, Decimal) else v for v in r] for r in data.rows[:limit]]
    return pd.DataFrame(rows, columns=data.columns)


def add_tables(new_tables: list[Table]) -> tuple[int, int]:
    existing = {t.key for t in project.tables}
    added, updated = merge_tables(project, new_tables)
    for _ in range(2):  # två varv: tidslogik mellan tabeller kräver att alla kategorier är satta
        for t in new_tables:
            infer_table(t, project)
    for t in new_tables:
        if t.key not in existing:
            t.rows = default_rows(t, project)
            default_fk_settings(t, project)
    changed()
    return added, updated


def smart_defaults(table: Table, col: Column, key: str) -> dict:
    d = defaults(key)
    other_dates = [c.name for c in table.columns if c is not col and c.kind in ("date", "datetime") and not c.computed]
    if key == "date.relative" and other_dates:
        d["base"] = other_dates[0]
    if key == "date.part" and other_dates:
        d["source"] = other_dates[0]
    if key == "number.decimal" and col.kind == "decimal" and col.scale is not None:
        d["decimals"] = col.scale
    if key == "list" and project.value_lists:
        d["list"] = next(iter(project.value_lists))
    if "via" in d and table.foreign_keys:  # generatorer som utgår från en förälder: välj första relationen
        fk = table.foreign_keys[0]
        d["via"] = fk.columns[0]
        ref = project.table(fk.ref_table)
        if ref and key == "parent.lookup":
            d["column"] = next((c.name for c in ref.columns if c.name not in fk.ref_columns), ref.columns[0].name)
        if ref and key == "date.after_parent":
            d["column"] = next((c.name for c in ref.columns if c.kind in ("date", "datetime")), "")
    if key == "choice.by":
        d["column"] = next((c.name for c in table.columns if c is not col and c.generator in ("choice", "list")), d["column"])
    return d


def set_generator(table: Table, col: Column, key: str):
    col.generator, col.params, col.manual, col.confidence = key, smart_defaults(table, col, key), True, ""


def param_summary(col: Column) -> str:
    spec = REGISTRY.get(col.generator)
    if not spec:
        return ""
    merged = {**defaults(col.generator), **(col.params or {})}
    parts = []
    for p in spec.params:
        v = merged.get(p.name)
        if p.name == "group" and not v:
            continue
        if p.type == "text":
            v = " / ".join(x.split("|")[0].strip() for x in str(v).splitlines() if x.strip())
        parts.append(f"{p.label}: {v}")
    text = ", ".join(parts)
    return text if len(text) <= 90 else text[:87] + "…"


def get_engine():
    c = ss.conn
    if c["mode"] == "SQL Server":
        if not c["server"] or not c["database"]:
            raise RuntimeError("Ange server och databas under '1. Källa'.")
        url = dbio.build_url(c["server"], c["database"], c["auth"], c["user"], ss.pw, c["driver"], c["encrypt"], c["trust"])
    else:
        if not c["url"]:
            raise RuntimeError("Ange en SQLAlchemy-URL under '1. Källa'.")
        url = c["url"]
    sig = str(url) + ss.pw
    if ss.get("_engine_sig") != sig:
        ss["_engine"], ss["_engine_sig"] = dbio.make_engine(url), sig
    return ss["_engine"]


def conn_label() -> str:
    c = ss.conn
    if c["mode"] == "SQL Server":
        return f"{c['server']} / {c['database']}" if c["server"] and c["database"] else ""
    return c["url"].split("@")[-1] if c["url"] else ""


# ---------------------------------------------------------------- sidopanel

def sidebar_projects():
    projects = store.list_projects()
    ids = [x["id"] for x in projects]
    if ss.project_id not in ids:  # borttaget i en annan flik
        ids.insert(0, ss.project_id)
    names = {x["id"]: x["name"] for x in projects}
    picked = st.selectbox("Projekt", ids, index=ids.index(ss.project_id), key=f"proj_pick_{ss.project_id}_{ss.ver}",
                          format_func=lambda i: names.get(i, project.name) or "(utan namn)",
                          help="Alla projekt sparas automatiskt i en lokal databas i repot (data/dummyfiller.db).")
    if picked != ss.project_id:
        loaded = store.load(picked)
        if loaded:
            use_project(loaded[0], picked, loaded[1])
            changed()
            st.rerun()
    project.name = st.text_input("Projektnamn", project.name, key=f"proj_name_{ss.project_id}_{ss.ver}")
    when = store.versions(ss.project_id, 1)
    st.caption("✔ Sparas automatiskt" + (f" · senast {when[0]['saved_at'][11:16]}" if when else ""))
    c1, c2 = st.columns(2)
    if c1.button("➕ Nytt", width="stretch", help="Skapar ett nytt, tomt projekt. Det nuvarande finns kvar i listan."):
        p = Project(name=f"Nytt projekt {len(projects) + 1}")
        use_project(p, *store.create(p))
        changed()
        st.rerun()
    if c2.button("📋 Kopiera", width="stretch", help="Skapar en kopia av projektet att experimentera i."):
        copy = Project.from_dict(project.to_dict())
        copy.name = f"{project.name} (kopia)"
        use_project(copy, *store.create(copy, f"Kopia av {project.name}"))
        changed()
        st.rerun()
    with st.expander("🕓 Historik"):
        vs = store.versions(ss.project_id)
        if len(vs) < 2:
            st.caption("Ingen tidigare version ännu. En ny version sparas när du har arbetat en stund.")
        else:
            labels = {v["id"]: f"{v['saved_at'][:16].replace('T', ' ')} · {v['tables']} tabeller" + (f" · {v['note']}" if v["note"] else "") for v in vs}
            vid = st.selectbox("Version", [v["id"] for v in vs], format_func=labels.get, key=f"ver_pick_{ss.project_id}_{ss.ver}")
            if st.button("Återställ den här versionen", width="stretch", help="Det nuvarande innehållet sparas först som en egen version, så att du kan ångra."):
                ss.project_hash = store.save(ss.project_id, project, ss.project_hash, "Före återställning")
                old = store.load_version(vid)
                old.name = project.name
                use_project(old, ss.project_id, store.save(ss.project_id, old, ss.project_hash, f"Återställd från {labels[vid][:16]}"))
                changed()
                st.rerun()
    with st.expander("📁 Fil (YAML)"):
        default_path = f"projekt/{project.name.strip().replace(' ', '_') or 'projekt'}.yaml"
        path = st.text_input("Projektfil", ss.get("project_path") or default_path,
                             help="För att dela projektet med teamet eller versionshantera det i git. Lösenord sparas aldrig.")
        c1, c2 = st.columns(2)
        if c1.button("Exportera", width="stretch"):
            try:
                project.connection = dict(ss.conn)
                project.save(path)
                ss.project_path = path
                st.success(f"Sparat till {path}")
            except Exception as e:
                st.error(f"Kunde inte spara: {e}")
        if c2.button("Importera", width="stretch", help="Finns ett projekt med samma namn uppdateras det, och det gamla innehållet finns kvar i historiken."):
            try:
                import_project(Project.load(path), f"Inläst från {path}")
                ss.project_path = path
                changed()
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte öppna: {e}")
    with st.expander("🗑️ Ta bort projektet"):
        st.caption("Projektet försvinner ur listan. Innehållet och historiken finns kvar i databasen.")
        if st.checkbox("Jag vill ta bort projektet", key=f"del_ok_{ss.project_id}") and st.button("Ta bort", width="stretch"):
            store.delete(ss.project_id)
            rest = store.last_project_id()
            loaded = store.load(rest) if rest else None
            if loaded:
                use_project(loaded[0], rest, loaded[1])
            else:
                use_project(Project(), *store.create(Project()))
            changed()
            st.rerun()


with st.sidebar:
    st.title("🧪 Dummyfiller")
    st.caption("Verklighetstrogen dummy-data utifrån dina scheman. Allt körs lokalt – ingen data hämtas från internet.")
    page = st.radio("Steg", PAGES, key="page")
    if st.query_params.get("steg") != str(PAGES.index(page) + 1):  # adressen visar steget, så att en omladdning stannar kvar
        st.query_params["steg"] = str(PAGES.index(page) + 1)
    st.divider()
    sidebar_projects()
    st.divider()
    included = [t for t in project.tables if t.include]
    st.metric("Tabeller som genereras", f"{len(included)} av {len(project.tables)}")
    st.metric("Rader totalt (ungefär)", f"{sum(estimated_rows(project, t) for t in included):,}".replace(",", " "))

for kind, text in ss.flash:
    getattr(st, kind)(text)
ss.flash = []


# ---------------------------------------------------------------- 1. Källa

def page_source():
    st.header("1. Källa – var kommer schemat ifrån?")
    st.write("Läs in tabeller från en databas eller ett DDL-skript, eller bygg dem själv. Källorna kan kombineras, "
             "och om du läser in samma tabell igen behålls dina egna inställningar.")
    tab_db, tab_ddl, tab_manual = st.tabs(["SQL Server", "DDL-skript", "Skapa själv"])

    with tab_db:
        c = ss.conn
        c["mode"] = st.radio("Anslutning", ["SQL Server", "Egen SQLAlchemy-URL"], index=0 if c["mode"] == "SQL Server" else 1, horizontal=True)
        if c["mode"] == "SQL Server":
            a, b = st.columns(2)
            c["server"] = a.text_input("Server", c["server"], help="T.ex. devsql01, devsql01\\INSTANS eller minserver.database.windows.net")
            c["database"] = b.text_input("Databas", c["database"])
            c["auth"] = a.selectbox("Inloggning", dbio.AUTH_MODES, index=dbio.AUTH_MODES.index(c["auth"]) if c["auth"] in dbio.AUTH_MODES else 0)
            drivers = dbio.list_drivers() or ["ODBC Driver 18 for SQL Server"]
            c["driver"] = b.selectbox("ODBC-drivrutin", drivers, index=drivers.index(c["driver"]) if c["driver"] in drivers else 0)
            if c["auth"] != dbio.AUTH_MODES[0]:
                c["user"] = a.text_input("Användare", c["user"])
            if c["auth"] == dbio.AUTH_MODES[1]:
                ss.pw = b.text_input("Lösenord", ss.pw, type="password", help="Sparas bara i minnet under sessionen, aldrig i projektfilen.")
            c["encrypt"] = a.checkbox("Kryptera anslutningen", c["encrypt"])
            c["trust"] = b.checkbox("Lita på serverns certifikat", c["trust"], help="Behövs ofta mot utvecklingsservrar med självsignerat certifikat.")
        else:
            c["url"] = st.text_input("SQLAlchemy-URL", c["url"], help="T.ex. sqlite:///C:/temp/test.db eller mssql+pyodbc://…")
        c["schemas"] = st.text_input("Scheman att läsa in (kommaseparerat, tomt = alla)", c["schemas"])
        st.caption("Endast metadata läses: tabeller, kolumner, datatyper, primärnycklar, främmande nycklar och unika index. Ingen tabelldata hämtas.")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Testa anslutning"):
            try:
                st.success(f"Anslutningen fungerar ({dbio.test_connection(get_engine())}).")
            except Exception as e:
                st.error(f"Anslutningen misslyckades: {e}")
        if b2.button("Läs in schema", type="primary"):
            try:
                schemas = [s.strip() for s in c["schemas"].split(",") if s.strip()] or None
                with st.spinner("Läser schema …"):
                    tables = dbio.reflect(get_engine(), schemas)
                added, updated = add_tables(tables)
                flash("success", f"Schemat är inläst: {added} nya tabeller, {updated} uppdaterade. Gå vidare till steg 2 för att se dem i diagrammet.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte läsa schemat: {e}")

    with tab_ddl:
        st.write("Ladda upp eller klistra in `CREATE TABLE`-skript (T-SQL, t.ex. skriptade från SSMS). `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` tolkas också.")
        files = st.file_uploader("SQL-filer", type=["sql", "txt", "ddl"], accept_multiple_files=True)
        pasted = st.text_area("… eller klistra in DDL", height=180)
        schema = st.text_input("Standardschema (för tabeller utan schema)", "dbo")
        b1, _ = st.columns([1, 4])
        sql = None
        if b1.button("Läs in DDL", type="primary"):
            sql = "\nGO\n".join([valuelists.decode(f.getvalue()) for f in files or []] + [pasted])
        examples = {"Vård": "vard.sql", "Ekonomi (kodplan, leverantörsfakturor, budget)": "ekonomi.sql",
                    "Personal (anställda, frånvaro, lön)": "personal.sql", "Tandvård": "tandvard.sql"}
        examples = {k: ROOT / "exempel" / v for k, v in examples.items() if (ROOT / "exempel" / v).exists()}
        if examples:
            st.divider()
            ex = st.selectbox("Exempelscheman att prova med", list(examples), key="example_pick")
            if st.button("Läs in exempelschema"):
                sql = examples[ex].read_text(encoding="utf-8")
        if sql is not None:
            tables, warns = parse_ddl(sql, schema or "dbo")
            if not tables:
                st.error("Hittade inga CREATE TABLE-satser att tolka.")
            else:
                added, updated = add_tables(tables)
                for w in warns:
                    flash("warning", w)
                flash("success", f"DDL inläst: {added} nya tabeller, {updated} uppdaterade. Gå vidare till steg 2 för att se dem i diagrammet.")
                st.rerun()

    with tab_manual:
        st.write("Du behöver inget schema för att komma igång. Under **2. Diagram** skapar du tabeller, kolumner och relationer "
                 "direkt i ett tabelldiagram – både egna tabeller och som komplettering "
                 "till inlästa. Egna tabeller kan skapas i databasen vid laddning eller exporteras till fil.")


# ---------------------------------------------------------------- 2. Diagram

_diagram = components.declare_component("dummyfiller_diagram", path=str(Path(__file__).resolve().parent / "diagram"))
TYPE_CHOICES = ["int", "bigint", "smallint", "tinyint", "bit", "decimal(18,2)", "decimal(10,2)", "nvarchar(50)", "nvarchar(100)",
                "nvarchar(200)", "nvarchar(max)", "varchar(20)", "char(13)", "date", "datetime2(0)", "time", "uniqueidentifier"]


def dg_select(table: str | None, column: str | None = None, add: bool = False):
    """Väljer tabell/kolumn i diagrammet från Python (diagrammet följer med via selNonce)."""
    ss.dg_sel = (table, column)
    ss.dg_add = table if add else None
    ss.dg_nonce = ss.get("dg_nonce", 0) + 1


def diagram_args(show_suggestions: bool, maximized: bool = False) -> dict:
    tables = []
    for t in project.tables:
        cols = []
        for c in t.columns:
            fk = t.fk_for(c.name)
            parent = project.table(fk.ref_table) if fk else None
            if c.computed:
                gen = "sätts av databasen"
            elif parent is not None:
                gen = "→ " + parent.name
            else:
                gen = REGISTRY[c.generator].label if c.generator in REGISTRY else ""
            cols.append({"name": c.name, "type": c.type_raw, "pk": c.name in t.primary_key, "fk": fk is not None,
                         "unique": any(c.name in u for u in t.uniques), "nullable": c.nullable, "gen": gen,
                         "low": c.confidence == "låg" and not c.manual and parent is None and not c.computed})
        cat = CATEGORIES.get(t.category, CATEGORIES["other"]).split(" (")[0]
        tables.append({"key": t.key, "name": t.name, "category": t.category, "include": t.include, "x": t.pos[0], "y": t.pos[1],
                       "rowsLabel": f"{estimated_rows(project, t):,} rader".replace(",", " "),
                       "sub": f"{cat}{' · ' + t.schema if t.schema else ''}{' · historik' if (t.history or {}).get('enabled') else ''}",
                       "columns": cols})
    keys = {t.key for t in project.tables}
    relations = []
    for t in project.tables:
        for fk in t.foreign_keys:
            if fk.ref_table in keys:
                label = f"{fk.per_parent_min}–{fk.per_parent_max} per förälder" if fk.per_parent_max else ""
                relations.append({"from": t.key, "fromCols": fk.columns, "to": fk.ref_table, "toCols": fk.ref_columns,
                                  "manual": fk.source == "manual", "label": label})
    sugg = [{"from": a, "col": b, "to": c, "toCol": d} for a, b, c, d in suggest_relations(project)] if show_suggestions else []
    sel = ss.get("dg_sel") or (None, None)
    cats = list(dict.fromkeys(t.category for t in project.tables))
    return {"tables": tables, "relations": relations, "suggestions": sugg, "selected": {"table": sel[0], "column": sel[1]},
            "selNonce": ss.get("dg_nonce", 0), "layoutNonce": ss.get("dg_layout", 0), "height": 680,
            "maximized": maximized, "fill": maximized,
            "legend": [[c, CATEGORIES.get(c, c).split(" (")[0].split(" / ")[0]] for c in cats][:6]}


def add_relation(a_key: str, a_col: str, b_key: str, b_col: str, flip: bool = True):
    level, msg, fk = edit.connect(project, a_key, a_col, b_key, b_col, flip)
    flash(level, msg)
    if fk is not None and level != "info":
        child = next(t for t in project.tables if fk in t.foreign_keys)
        infer_table(child, project)
        default_fk_settings(child, project)
        changed()
        dg_select(child.key, fk.columns[0])


def handle_diagram_event(ev: dict):
    kind = ev.get("type")
    if kind == "select":
        ss.dg_sel, ss.dg_add = (ev.get("table"), ev.get("column")), None
    elif kind == "move":
        for key, xy in (ev.get("positions") or {}).items():
            t = project.table(key)
            if t is not None and len(xy) == 2:
                t.pos = [float(xy[0]), float(xy[1])]
    elif kind == "connect":
        add_relation(ev["from"], ev["col"], ev["to"], ev["toCol"])
    elif kind == "accept":
        add_relation(ev["from"], ev["col"], ev["to"], ev["toCol"], flip=False)
    elif kind == "maximize":
        ss.dg_max = bool(ev.get("on"))
    elif kind == "add_column":
        ss.dg_sel, ss.dg_add = (ev.get("table"), None), ev.get("table")


def generator_settings(t: Table, col: Column):
    """Generator, parametrar och andel NULL för en kolumn. Ändringar gäller direkt."""
    labels = GEN_LABELS
    cur_label = label_of(col.generator) if col.generator in REGISTRY else labels[0]
    if col.generator.startswith(library.PREFIX) and col.generator not in REGISTRY:
        st.warning(f"Generatorn '{col.generator}' finns inte längre. Välj en annan, eller läs in den under 6. Generatorer.")
    elif col.generator.startswith(library.PREFIX) and library.origin(col.generator):
        st.info("Den egna generatorn finns inte i ditt bibliotek, men projektet har en kopia av den. Lägg till den under 6. Generatorer.")
    picked = st.selectbox("Generator", labels, index=labels.index(cur_label), key=f"gen_{t.key}_{col.name}_{ss.ver}",
                          help="Skriv i rutan för att söka, t.ex. 'datum', 'konto' eller 'diagnos'. Saknas något? Bygg en egen generator under 6. Generatorer.")
    if LABEL_TO_KEY[picked] != col.generator:
        set_generator(t, col, LABEL_TO_KEY[picked])
        changed()
        st.rerun()
    spec = REGISTRY[col.generator]
    if spec.help:
        st.caption(spec.help)
    new_params = param_widgets(t, col)
    if new_params != {**defaults(col.generator), **(col.params or {})}:
        col.params, col.manual, col.confidence = new_params, True, ""
        ss.result = None
        st.rerun()
    if col.nullable and col.name not in t.primary_key:
        np_ = st.slider("Andel NULL %", 0, 100, int(col.null_pct), 5, key=f"null_{t.key}_{col.name}_{ss.ver}")
        if np_ != int(col.null_pct):
            col.null_pct = float(np_)
            ss.result = None
            st.rerun()
    if col.manual and st.button("↩️ Återställ till automatiskt förslag"):
        col.generator, col.params, col.confidence, col.null_pct = infer_column(col, t, project)
        col.manual = False
        changed()
        st.rerun()


def new_table_form(key: str):
    with st.form(key, clear_on_submit=True):
        x, y = st.columns([1, 2])
        schema = x.text_input("Schema", "dbo")
        name = y.text_input("Tabellnamn")
        cat = st.selectbox("Kategori", ["Automatiskt utifrån namnet"] + CAT_LABELS)
        add_id = st.checkbox("Lägg till ID-kolumn (int, primärnyckel)", True)
        if st.form_submit_button("Skapa tabell", type="primary"):
            name = name.strip()
            if not name:
                st.error("Ange ett tabellnamn.")
            elif project.table(f"{schema.strip()}.{name}" if schema.strip() else name):
                st.error("Tabellen finns redan.")
            else:
                t = Table(name=name, schema=schema.strip(), custom=True)
                if add_id:
                    t.columns.append(Column.from_type(f"{name}ID", "int", nullable=False, identity=True, custom=True))
                    t.primary_key = [f"{name}ID"]
                if cat in CAT_BY_LABEL:
                    t.category, t.category_manual = CAT_BY_LABEL[cat], True
                project.tables.append(t)
                infer_table(t, project, set_rows=True)
                select("cur_table", t.key)
                dg_select(t.key, None, add=True)
                changed()
                st.rerun()


def add_column_form(t: Table):
    with st.form(f"dg_addcol_{t.key}", clear_on_submit=True):
        name = st.text_input("Kolumnnamn", help="Namnet styr förslaget på innehåll, t.ex. Fornamn, Kontonr, Fakturadatum eller Diagnoskod.")
        typ = st.selectbox("Datatyp", TYPE_CHOICES, index=TYPE_CHOICES.index("nvarchar(100)"), accept_new_options=True,
                           help="Välj i listan eller skriv en egen, t.ex. decimal(12,4).")
        a, b = st.columns(2)
        nullable = a.checkbox("Tillåt NULL", True)
        in_pk = b.checkbox("Primärnyckel", False)
        if st.form_submit_button("Lägg till kolumn", type="primary"):
            name = name.strip()
            col = Column.from_type(name, str(typ).strip() or "nvarchar(100)", nullable=nullable and not in_pk, custom=True) if name else None
            if col is None or t.column(name):
                st.error("Ange ett kolumnnamn som inte redan finns.")
            elif col.kind == "other":
                st.error(f"Okänd datatyp: {typ}")
            else:
                t.columns.append(col)
                if in_pk:
                    t.primary_key.append(name)
                col.generator, col.params, col.confidence, col.null_pct = infer_column(col, t, project)
                changed()
                dg_select(t.key, name, add=True)
                st.rerun()


def panel_table(t: Table):
    st.subheader(t.name)
    st.caption(f"{CATEGORIES.get(t.category, '')} · {len(t.columns)} kolumner · {'egen tabell' if t.custom else 'från schema'}")
    with st.expander("➕ Lägg till kolumn", expanded=ss.get("dg_add") == t.key or not t.columns):
        add_column_form(t)
    with st.form(f"dg_table_{t.key}_{ss.ver}"):
        a, b = st.columns([1, 2])
        schema = a.text_input("Schema", t.schema)
        name = b.text_input("Tabellnamn", t.name)
        cat = st.selectbox("Kategori", CAT_LABELS, index=CAT_LABELS.index(CATEGORIES.get(t.category, CATEGORIES["other"])),
                           help="Styr hur kolumnerna tolkas. Kolumner som du inte har anpassat själv får nya förslag när kategorin ändras.")
        rows = st.number_input("Antal rader", 0, 10_000_000, int(t.rows), help="Antal unika om tabellen har historik. Styrs av föräldern om en relation har 'barn per förälder'.")
        include = st.checkbox("Ta med vid generering", t.include)
        if st.form_submit_button("Spara tabellen"):
            try:
                if name.strip():
                    old = t.key
                    edit.rename_table(project, t, name.strip(), schema.strip())
                    if t.key != old:
                        dg_select(t.key, None)
                        select("cur_table", t.key)
                t.rows, t.include = int(rows), include
                if CAT_BY_LABEL[cat] != t.category:
                    t.category, t.category_manual = CAT_BY_LABEL[cat], True
                    infer_table(t, project)
                    t.rows = default_rows(t, project)
                changed()
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    with st.expander("🕓 Historik (SCD2)" + (" – på" if (t.history or {}).get("enabled") else "")):
        history_form(t)
    with st.expander("🗑️ Ta bort tabellen"):
        st.caption("Tabellen tas bort ur projektet tillsammans med relationer till och från den. Databasen påverkas inte.")
        if st.button("Ta bort ur projektet", key=f"dg_del_{t.key}"):
            project.remove_table(t.key)
            dg_select(None)
            changed()
            st.rerun()


def panel_relation(t: Table, fk: ForeignKey):
    k = f"{t.key}_{fk.columns[0]}_{ss.ver}"
    st.markdown(f"**Relation** → {fk.ref_table} ({', '.join(fk.ref_columns)})")
    dist = st.selectbox("Fördelning över föräldrar", DIST_LABELS, index=DIST_LABELS.index(DISTRIBUTIONS.get(fk.distribution, DIST_LABELS[0])), key=f"dg_dist_{k}")
    a, b = st.columns(2)
    pmin = int(a.number_input("Barn per förälder, minst", 0, 1000, int(fk.per_parent_min), key=f"dg_pmin_{k}"))
    pmax = int(b.number_input("… högst", 0, 1000, int(fk.per_parent_max), key=f"dg_pmax_{k}",
                              help="Större än 0: varje förälder får så här många barnrader och tabellens radantal följer av föräldern. 0 = använd tabellens radantal."))
    nullable = all((c := t.column(n)) is not None and c.nullable for n in fk.columns)
    null_pct = float(st.slider("Andel utan förälder (NULL) %", 0, 100, int(fk.null_pct), 5, key=f"dg_fknull_{k}", disabled=not nullable))
    guided = st.checkbox("Välj förälder utifrån kolumnens generator", fk.guided, key=f"dg_guided_{k}",
                         help="För kodkolumner: föräldern väljs så att t.ex. diagnosen passar patienten eller kontot passar fakturan.")
    new = (DIST_BY_LABEL[dist], pmin, pmax, null_pct, guided)
    if new != (fk.distribution, fk.per_parent_min, fk.per_parent_max, fk.null_pct, fk.guided):
        fk.distribution, fk.per_parent_min, fk.per_parent_max, fk.null_pct, fk.guided = new
        changed()
        st.rerun()
    if st.button("Ta bort relationen", key=f"dg_delrel_{k}"):
        t.foreign_keys.remove(fk)
        infer_table(t, project)
        changed()
        st.rerun()


def panel_column(t: Table, col: Column):
    st.subheader(f"{t.name}.{col.name}")
    st.caption(" · ".join(x for x in (col.type_raw + ("" if col.nullable else " NOT NULL"), key_label(t, col)) if x))
    fk = t.fk_for(col.name)
    has_parent = fk is not None and project.table(fk.ref_table) is not None
    if col.computed:
        st.info("Kolumnen sätts av databasen (beräknad kolumn eller rowversion) och genereras inte.")
    else:
        if has_parent:
            panel_relation(t, fk)
        if not has_parent or fk.guided:
            if has_parent:
                st.divider()
            generator_settings(t, col)
    with st.expander("✏️ Namn och datatyp"):
        with st.form(f"dg_col_{t.key}_{col.name}_{ss.ver}"):
            name = st.text_input("Kolumnnamn", col.name)
            opts = TYPE_CHOICES if col.type_raw in TYPE_CHOICES else [col.type_raw] + TYPE_CHOICES
            typ = st.selectbox("Datatyp", opts, index=opts.index(col.type_raw), accept_new_options=True)
            a, b = st.columns(2)
            nullable = a.checkbox("Tillåt NULL", col.nullable)
            in_pk = b.checkbox("Primärnyckel", col.name in t.primary_key)
            if st.form_submit_button("Spara kolumnen"):
                try:
                    new_name = name.strip() or col.name
                    edit.rename_column(project, t, col.name, new_name)
                    if str(typ).strip() and str(typ).strip() != col.type_raw:
                        info = parse_type(str(typ).strip())
                        if info["kind"] == "other":
                            raise ValueError(f"Okänd datatyp: {typ}")
                        col.type_raw, col.kind, col.length, col.precision, col.scale = str(typ).strip(), info["kind"], info["length"], info["precision"], info["scale"]
                    if in_pk and col.name not in t.primary_key:
                        t.primary_key.append(col.name)
                    elif not in_pk and col.name in t.primary_key:
                        t.primary_key.remove(col.name)
                    col.nullable = nullable and not in_pk
                    if not col.manual:  # nytt namn eller ny typ kan ge ett bättre förslag
                        col.generator, col.params, col.confidence, col.null_pct = infer_column(col, t, project)
                    changed()
                    dg_select(t.key, col.name)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    if st.button("🗑️ Ta bort kolumnen", key=f"dg_delcol_{t.key}_{col.name}"):
        edit.delete_column(project, t, col.name)
        dg_select(t.key, None)
        changed()
        st.rerun()


MAX_CSS = """<style>
section[data-testid="stSidebar"], [data-testid="stExpandSidebarButton"], header[data-testid="stHeader"] { display: none !important; }
[data-testid="stMainBlockContainer"] { padding: .6rem 1rem 1rem !important; max-width: 100% !important; }
[data-testid="stColumn"]:has(.dg-panel) { position: sticky; top: .6rem; align-self: flex-start; max-height: calc(100vh - 1.2rem);
    overflow-y: auto; padding-right: .4rem; }
</style>"""


def page_diagram():
    ss.setdefault("dg_max", False)
    ss.setdefault("dg_sel", (None, None))
    ss.setdefault("dg_seq", None)
    ss.setdefault("dg_add", None)
    pending = ss.get("diagram_cmp")  # händelsen som startade den här körningen
    if isinstance(pending, dict) and pending.get("seq") != ss.dg_seq:
        ss.dg_seq = pending.get("seq")
        handle_diagram_event(pending)
    maxed = bool(ss.dg_max)
    if maxed:  # maximerat: dölj sidomeny, sidhuvud och rubrik och använd hela fönstret
        st.html(MAX_CSS)
    else:
        st.header("2. Diagram – tabeller, kolumner och relationer")
    for kind, text in ss.flash:  # meddelanden från händelsen (t.ex. "Relation skapad") visas direkt
        getattr(st, kind)(text)
    ss.flash = []
    edit.auto_layout(project)

    a, b, c, d = st.columns([1.5, 1.2, 1.1, 3])
    n_sugg = len(suggest_relations(project)) if project.tables else 0
    show = a.toggle(f"Visa förslag på relationer ({n_sugg})", key="dg_show_sugg", disabled=not n_sugg,
                    help="Förslag utifrån kolumnnamn, t.ex. PatientID → Patient. Visas som streckade pilar; klicka på plustecknet för att lägga till.")
    if b.button("Ordna automatiskt", help="Placerar om alla tabeller: föräldrar till vänster, barn till höger."):
        edit.auto_layout(project, only_missing=False)
        ss.dg_layout = ss.get("dg_layout", 0) + 1
    with c.popover("➕ Ny tabell"):
        new_table_form("dg_new_table")
    if maxed:
        d.caption("Maximerat läge · Esc eller ✕ i diagrammet går tillbaka")

    left, right = st.columns([3.6, 1] if maxed else [2.7, 1], gap="medium")
    with left:
        ev = _diagram(**diagram_args(bool(show) and n_sugg > 0, maxed), key="diagram_cmp", default=None)
        if isinstance(ev, dict) and ev.get("seq") != ss.dg_seq:  # reserv om händelsen inte fanns i sessionen vid start
            ss.dg_seq = ev.get("seq")
            handle_diagram_event(ev)
            st.rerun()
    tkey, cname = ss.dg_sel
    t = project.table(tkey) if tkey else None
    col = t.column(cname) if t is not None and cname else None
    with right:
        if maxed:
            st.html('<span class="dg-panel"></span>')  # panelen följer med när sidan rullas
        if t is None:
            st.subheader("Så här gör du")
            st.markdown(
                "- **Klicka** på en tabell eller kolumn för att redigera den här i panelen.\n"
                "- **Dra i rubriken** för att flytta en tabell. Placeringen sparas i projektet.\n"
                "- **Dra från pricken** till höger om en kolumn till en kolumn i en annan tabell för att skapa en relation. "
                "Pilen pekar på föräldern, och dras den från en nyckel vänds den automatiskt.\n"
                "- **Klicka på en pil** för att ändra eller ta bort relationen.\n"
                "- **⛶ Maximera** i diagrammets verktygsrad låter diagrammet fylla hela fönstret.\n"
                "- Kolumner märkta ⚠ är gissningar som är värda att titta på.")
            if show and n_sugg and st.button(f"Lägg till alla {n_sugg} föreslagna relationer", type="primary"):
                for s in suggest_relations(project):
                    add_relation(*s, flip=False)
                dg_select(None)
                st.rerun()
            if not project.tables:
                st.info("Inga tabeller ännu. Skapa en med **➕ Ny tabell** eller läs in ett schema under steg 1.")
        elif col is None:
            panel_table(t)
        else:
            panel_column(t, col)
    if t is not None and t.columns:
        with left:
            st.caption(f"Förhandsgranskning av {t.key}")
            try:
                res = generate(project, only=[t.key], max_rows=8)
                st.dataframe(to_df(res.data[t.key]), hide_index=True, width="stretch")
                for w in res.warnings:
                    if w.startswith(t.key):
                        st.warning(w)
            except Exception as e:
                st.error(f"Förhandsgranskningen misslyckades: {e}")


# ---------------------------------------------------------------- 3. Tabeller och relationer

def fk_rows() -> list[tuple[Table, ForeignKey]]:
    return [(t, fk) for t in project.tables for fk in t.foreign_keys]


def diagram_dot() -> str:
    lines = ['digraph G {', 'rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fillcolor="#eef1f5", color="#8b95a5", fontname="Helvetica", fontsize=11, fontcolor="#1f2933"];',
             'edge [color="#7b8794", arrowsize=0.7, fontname="Helvetica", fontsize=9, fontcolor="#7b8794"];']
    keys = {t.key for t in project.tables if t.include}
    for t in project.tables:
        if t.include:
            cat = CATEGORIES.get(t.category, "").split(" (")[0].split(" / ")[0]
            lines.append(f'"{t.key}" [label="{t.key}\\n{cat} · {estimated_rows(project, t)} rader"];')
    for t in project.tables:
        for fk in t.foreign_keys:
            if t.key in keys and fk.ref_table in keys:
                style = ', style=dashed' if fk.source == "manual" else ""
                per = f" ({fk.per_parent_min}–{fk.per_parent_max} per förälder)" if fk.per_parent_max else ""
                lines.append(f'"{t.key}" -> "{fk.ref_table}" [label="{", ".join(fk.columns)}{per}"{style}];')
    return "\n".join(lines + ["}"])


def page_tables():
    st.header("3. Tabeller och relationer")
    # --- ta emot redigeringar innan tabellerna ritas om
    dirty = False
    for idx, change in take_edits("tables").items():
        t = project.tables[int(idx)]
        if "Ta med" in change:
            t.include = bool(change["Ta med"])
        if "Rader" in change and change["Rader"] is not None:
            t.rows = max(0, int(change["Rader"]))
        if "Kategori" in change and change["Kategori"] in CAT_BY_LABEL:
            t.category, t.category_manual = CAT_BY_LABEL[change["Kategori"]], True
            infer_table(t, project)  # nya förslag för kolumner som inte ändrats manuellt
            t.rows = default_rows(t, project)
        dirty = True
    rels = fk_rows()
    for idx, change in take_edits("rels").items():
        t, fk = rels[int(idx)]
        if change.get("Ta bort"):
            t.foreign_keys.remove(fk)
            infer_table(t, project)
        if "Fördelning" in change and change["Fördelning"] in DIST_BY_LABEL:
            fk.distribution = DIST_BY_LABEL[change["Fördelning"]]
        if "Andel NULL %" in change and change["Andel NULL %"] is not None:
            fk.null_pct = float(change["Andel NULL %"])
        if "Barn per förälder, minst" in change and change["Barn per förälder, minst"] is not None:
            fk.per_parent_min = max(0, int(change["Barn per förälder, minst"]))
        if "Barn per förälder, högst" in change and change["Barn per förälder, högst"] is not None:
            fk.per_parent_max = max(0, int(change["Barn per förälder, högst"]))
        if "Styrd" in change:
            fk.guided = bool(change["Styrd"])
        dirty = True
    if dirty:
        changed()

    if not project.tables:
        st.info("Inga tabeller ännu. Läs in ett schema under steg 1 eller skapa en tabell här nedanför.")
    else:
        st.write("Kategorin styr hur kolumnerna tolkas och hur många rader som föreslås. Ändrar du kategori får kolumner "
                 "som du inte själv har anpassat nya förslag.")
        df = pd.DataFrame([{
            "Ta med": t.include, "Tabell": t.key, "Kategori": CATEGORIES.get(t.category, CATEGORIES["other"]), "Rader": t.rows,
            "Blir ungefär": estimated_rows(project, t), "Kolumner": len(t.columns), "Beror på": ", ".join(sorted({fk.ref_table for fk in t.foreign_keys})),
            "Osäkra kolumner": sum(1 for c in t.columns if c.confidence == "låg" and not c.manual and t.fk_for(c.name) is None),
            "Källa": "egen" if t.custom else "schema",
        } for t in project.tables])
        editor("tables", df, disabled=["Tabell", "Blir ungefär", "Kolumner", "Beror på", "Osäkra kolumner", "Källa"], column_config={
            "Kategori": st.column_config.SelectboxColumn(options=CAT_LABELS, required=True, width="medium"),
            "Rader": st.column_config.NumberColumn(min_value=0, step=1, help="Antal rader som ska genereras (antal unika om tabellen har historik)."),
            "Blir ungefär": st.column_config.NumberColumn(help="Faktiskt radantal när 'barn per förälder' eller historik (SCD2) styr."),
            "Osäkra kolumner": st.column_config.NumberColumn(help="Kolumner där den automatiska tolkningen är en gissning – titta på dem under steg 4."),
        })
        order, broken = load_order(project, [t.key for t in project.tables if t.include])
        st.caption("Laddordning (föräldrar före barn): " + " → ".join(order))
        for key, fk in broken:
            st.warning(f"Cirkulär relation: {key} ({', '.join(fk.columns)}) → {fk.ref_table}. Relationen fylls i efteråt eller sätts till NULL.")
        with st.expander("🗺️ Relationsdiagram"):
            st.graphviz_chart(diagram_dot(), width="stretch")
            st.caption("Pilarna går från barn till förälder. Streckade pilar är egna relationer som inte finns deklarerade i schemat.")

    a, b = st.columns(2)
    with a.expander("➕ Ny tabell"):
        with st.form("new_table", clear_on_submit=True):
            x, y = st.columns([1, 2])
            schema = x.text_input("Schema", "dbo")
            name = y.text_input("Tabellnamn")
            cat = st.selectbox("Kategori", ["Automatiskt utifrån namnet"] + CAT_LABELS)
            add_id = st.checkbox("Lägg till ID-kolumn (int, primärnyckel)", True)
            if st.form_submit_button("Skapa tabell"):
                name = name.strip()
                if not name:
                    st.error("Ange ett tabellnamn.")
                elif project.table(f"{schema}.{name}" if schema else name):
                    st.error("Tabellen finns redan.")
                else:
                    t = Table(name=name, schema=schema.strip(), custom=True)
                    if add_id:
                        t.columns.append(Column.from_type(f"{name}ID", "int", nullable=False, identity=True, custom=True))
                        t.primary_key = [f"{name}ID"]
                    if cat in CAT_BY_LABEL:
                        t.category, t.category_manual = CAT_BY_LABEL[cat], True
                    project.tables.append(t)
                    infer_table(t, project, set_rows=True)
                    select("cur_table", t.key)
                    changed()
                    flash("success", f"Tabellen {t.key} är skapad. Lägg till kolumner under steg 4.")
                    st.rerun()
    with b.expander("🗑️ Ta bort tabell"):
        if project.tables:
            victim = st.selectbox("Tabell", [t.key for t in project.tables], key="del_table")
            st.caption("Tabellen tas bara bort ur projektet – databasen påverkas inte. Vill du bara hoppa över den, avmarkera 'Ta med'.")
            if st.button("Ta bort ur projektet"):
                project.remove_table(victim)
                changed()
                st.rerun()

    st.subheader("Relationer")
    if rels:
        st.write("Främmande nycklar fylls alltid med värden som finns i föräldratabellen. Fördelningen styr hur barnraderna sprids över föräldrarna.")
        df = pd.DataFrame([{
            "Ta bort": False, "Tabell": t.key, "Kolumner": ", ".join(fk.columns), "Förälder": fk.ref_table,
            "Föräldrakolumner": ", ".join(fk.ref_columns), "Fördelning": DISTRIBUTIONS.get(fk.distribution, DIST_LABELS[0]),
            "Barn per förälder, minst": fk.per_parent_min, "Barn per förälder, högst": fk.per_parent_max,
            "Andel NULL %": fk.null_pct, "Styrd": fk.guided, "Källa": "egen" if fk.source == "manual" else "schema",
        } for t, fk in rels])
        editor("rels", df, disabled=["Tabell", "Kolumner", "Förälder", "Föräldrakolumner", "Källa"], column_config={
            "Fördelning": st.column_config.SelectboxColumn(options=DIST_LABELS, required=True, width="large"),
            "Andel NULL %": st.column_config.NumberColumn(min_value=0, max_value=100, step=5, help="Gäller bara om FK-kolumnen tillåter NULL."),
            "Barn per förälder, minst": st.column_config.NumberColumn(min_value=0, step=1),
            "Barn per förälder, högst": st.column_config.NumberColumn(min_value=0, step=1, help="Större än 0: varje förälder får så här många barnrader, och tabellens radantal följer av föräldern (t.ex. 1–5 fakturarader per faktura). 0 = använd tabellens radantal och fördelningen."),
            "Styrd": st.column_config.CheckboxColumn(help="Föräldern väljs utifrån värdet som kolumnens egen generator ger. Används för kodkolumner, så att t.ex. diagnosen passar patienten och vårdkontakten."),
        })
    else:
        st.caption("Inga relationer ännu.")

    a, b = st.columns(2)
    with a.expander("➕ Ny relation"):
        keys = [t.key for t in project.tables]
        if len(keys) >= 1:
            child = project.table(st.selectbox("Barntabell (har den främmande nyckeln)", keys, key="rel_child"))
            parent = project.table(st.selectbox("Föräldratabell", keys, key="rel_parent"))
            ccols = st.multiselect("Kolumn(er) i barntabellen", [c.name for c in child.columns if not c.computed], key=f"rel_ccols_{child.key}")
            pcols = st.multiselect("Kolumn(er) i föräldratabellen", [c.name for c in parent.columns], default=parent.primary_key, key=f"rel_pcols_{parent.key}")
            if st.button("Lägg till relation"):
                if not ccols or len(ccols) != len(pcols):
                    st.error("Välj lika många kolumner i barn- och föräldratabellen.")
                else:
                    child.foreign_keys.append(ForeignKey(columns=ccols, ref_table=parent.key, ref_columns=pcols, source="manual"))
                    infer_table(child, project)
                    changed()
                    st.rerun()
    with b.expander("💡 Föreslå relationer utifrån kolumnnamn"):
        st.caption("Användbart när databasen saknar deklarerade främmande nycklar, vilket är vanligt i data warehouse.")
        sugg = suggest_relations(project)
        if not sugg:
            st.write("Inga förslag hittades.")
        picks = [s for s in sugg if st.checkbox(f"{s[0]}.{s[1]} → {s[2]}.{s[3]}", True, key=f"sugg_{s[0]}_{s[1]}_{s[2]}")]
        if sugg and st.button("Lägg till valda relationer"):
            for tkey, col, rkey, rcol in picks:
                t = project.table(tkey)
                t.foreign_keys.append(ForeignKey(columns=[col], ref_table=rkey, ref_columns=[rcol], source="manual"))
            for tkey in {p[0] for p in picks}:
                infer_table(project.table(tkey), project)
            changed()
            st.rerun()


# ---------------------------------------------------------------- 4. Kolumner

def key_label(t: Table, c: Column) -> str:
    parts = []
    if c.name in t.primary_key:
        parts.append("PK")
    fk = t.fk_for(c.name)
    if fk:
        parts.append(f"FK → {fk.ref_table}")
    if any(c.name in u for u in t.uniques):
        parts.append("unik")
    if c.identity:
        parts.append("identity")
    return ", ".join(parts)


def gen_label(t: Table, c: Column) -> str:
    if c.computed:
        return COMPUTED_LABEL
    fk = t.fk_for(c.name)
    if fk and project.table(fk.ref_table) is not None:
        return f"Relation → {fk.ref_table}"
    return label_of(c.generator) if c.generator in REGISTRY else ""


def param_widgets(t: Table, col: Column) -> dict:
    """Ritar ett formulär för generatorns parametrar och returnerar de nya värdena."""
    spec = REGISTRY[col.generator]
    cur = {**defaults(col.generator), **(col.params or {})}
    out = {}
    others = [c.name for c in t.columns if c is not col and not c.computed]
    for p in spec.params:
        k = f"p_{t.key}_{col.name}_{col.generator}_{p.name}_{ss.ver}"
        v = cur.get(p.name, p.default)
        h = p.help or None
        if p.type == "fk":
            opts = [""] + [c for fk in t.foreign_keys for c in fk.columns]
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k, help=h,
                                       format_func=lambda x: x or "(ingen)")
        elif p.type == "parent_column":
            fk = t.fk_for(out.get(p.via, "")) if out.get(p.via) else None
            ref = project.table(fk.ref_table) if fk else None
            opts = [""] + ([c.name for c in ref.columns] if ref else [])
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k + str(out.get(p.via)), help=h,
                                       format_func=lambda x: x or "(ingen)")
        elif p.type == "int":
            out[p.name] = int(st.number_input(p.label, value=int(v), step=1, key=k, help=h))
        elif p.type == "float":
            out[p.name] = float(st.number_input(p.label, value=float(v), key=k, help=h))
        elif p.type == "bool":
            out[p.name] = st.checkbox(p.label, bool(v), key=k, help=h)
        elif p.type == "select":
            opts = list(p.options or [])
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k, help=h)
        elif p.type == "text":
            out[p.name] = st.text_area(p.label, str(v), height=160, key=k, help=h)
        elif p.type == "column":
            opts = others or [""]
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k, help=h)
        elif p.type == "list":
            opts = list(project.value_lists) or [""]
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k, help=h)
            if not project.value_lists:
                st.caption("Inga värdelistor inlästa ännu – gör det under steg 5.")
        else:
            out[p.name] = st.text_input(p.label, str(v), key=k, help=h)
    return out


def history_form(t: Table):
    h = dict(t.history or {})
    st.caption("För dimensioner med historik: varje unik rad får flera versioner med giltighetstid som inte överlappar. "
               "Tabellens radantal anger då antalet unika (affärsnycklar).")
    dates = [c.name for c in t.columns if c.kind in ("date", "datetime") and not c.computed]
    flags = ["(ingen)"] + [c.name for c in t.columns if c.kind in ("bool", "int") and not c.computed and c.name not in t.primary_key]
    if len(dates) < 2:
        st.info("Tabellen behöver två datumkolumner (giltig från och giltig till).")
        return
    k = f"{t.key}_{ss.ver}"
    enabled = st.checkbox("Generera flera versioner per rad", bool(h.get("enabled")), key=f"h_on_{k}")
    a, b = st.columns(2)
    f = a.selectbox("Giltig från", dates, index=dates.index(h["from"]) if h.get("from") in dates else 0, key=f"h_f_{k}")
    to = b.selectbox("Giltig till", dates, index=dates.index(h["to"]) if h.get("to") in dates else 1, key=f"h_t_{k}")
    cur = st.selectbox("Flagga för aktuell version", flags, index=flags.index(h["current"]) if h.get("current") in flags else 0, key=f"h_c_{k}")
    vmin = int(a.number_input("Versioner, minst", 1, 20, int(h.get("min", 1)), key=f"h_min_{k}"))
    vmax = int(b.number_input("Versioner, högst", 1, 20, int(h.get("max", 3)), key=f"h_max_{k}"))
    free = [c.name for c in t.columns if not c.computed and c.name not in t.primary_key and c.name not in (f, to, cur)]
    changing = st.multiselect("Kolumner som ändras mellan versioner", free, default=[c for c in h.get("changing") or [] if c in free], key=f"h_ch_{k}",
                              help="Lämna tomt för automatiskt val: adress, telefon, e-post, värdelistor och tal. Övriga kolumner är lika i alla versioner.")
    open_end = st.selectbox("Giltig till för aktuell version", ["NULL", "9999-12-31"], index=1 if h.get("open_end") == "9999-12-31" else 0, key=f"h_o_{k}")
    new = {"enabled": enabled, "from": f, "to": to, "current": "" if cur == "(ingen)" else cur, "min": vmin, "max": max(vmin, vmax),
           "changing": changing, "open_end": open_end}
    if new != h and st.button("Spara historikinställningar", key=f"h_save_{k}"):
        t.history = new
        changed()
        st.rerun()


def page_columns():
    st.header("4. Kolumner – vad ska varje kolumn innehålla?")
    if not project.tables:
        st.info("Inga tabeller ännu. Börja med steg 1 eller skapa en tabell under steg 3.")
        return
    keys = [t.key for t in project.tables]
    t = project.table(pick("Tabell", keys, "cur_table"))
    grid_name = f"cols_{t.key}"

    dirty = False
    for idx, change in take_edits(grid_name).items():
        col = t.columns[int(idx)]
        new = change.get("Generator")
        if new in LABEL_TO_KEY and LABEL_TO_KEY[new] != col.generator and not col.computed:
            set_generator(t, col, LABEL_TO_KEY[new])
            select("cur_col", col.name)
        if "Andel NULL %" in change and change["Andel NULL %"] is not None:
            col.null_pct = float(change["Andel NULL %"])
        dirty = True
    if dirty:
        changed()

    st.caption(f"Kategori: {CATEGORIES.get(t.category)} · {t.rows} rader · Varje kolumn har fått ett förslag utifrån namn, datatyp och tabellens kategori. "
               "Byt generator direkt i tabellen, eller finjustera under 'Anpassa kolumn'.")
    if t.columns:
        fk_labels = sorted({gen_label(t, c) for c in t.columns if gen_label(t, c).startswith("Relation")})
        df = pd.DataFrame([{
            "Kolumn": c.name, "Typ": c.type_raw + ("" if c.nullable else " NOT NULL"), "Nyckel": key_label(t, c),
            "Generator": gen_label(t, c), "Inställningar": "" if gen_label(t, c).startswith(("Relation", "(")) else param_summary(c),
            "Andel NULL %": c.null_pct,
            "Tolkning": "egen" if c.manual else "" if c.computed or t.fk_for(c.name) else ("säker" if c.confidence == "hög" else "gissning ⚠"),
        } for c in t.columns])
        editor(grid_name, df, disabled=["Kolumn", "Typ", "Nyckel", "Inställningar", "Tolkning"], column_config={
            "Generator": st.column_config.SelectboxColumn(options=GEN_LABELS + fk_labels + [COMPUTED_LABEL], required=True, width="large"),
            "Andel NULL %": st.column_config.NumberColumn(min_value=0, max_value=100, step=5, help="Gäller bara kolumner som tillåter NULL."),
            "Tolkning": st.column_config.TextColumn(help="'gissning' betyder att namnet inte gav någon tydlig ledtråd – kontrollera de kolumnerna."),
        })
    else:
        st.info("Tabellen har inga kolumner ännu. Lägg till kolumner här nedanför.")
    if t.checks:
        st.caption("CHECK-villkor i schemat (enkla villkor har redan styrt förslagen): " + " · ".join(f"`{c}`" for c in t.checks[:6]))

    left, right = st.columns([1, 1.5], gap="large")
    with left:
        st.subheader("Anpassa kolumn")
        names = [c.name for c in t.columns if not c.computed]
        if names:
            col = t.column(pick("Kolumn", names, "cur_col"))
            fk = t.fk_for(col.name)
            if fk and project.table(fk.ref_table) is not None:
                st.info(f"Kolumnen är en främmande nyckel och får värden från **{fk.ref_table}** ({', '.join(fk.ref_columns)}). "
                        "Fördelning och andel NULL ställer du in under steg 3 → Relationer.")
            else:
                generator_settings(t, col)
    with right:
        st.subheader("Förhandsgranskning")
        try:
            res = generate(project, only=[t.key], max_rows=12)
            st.dataframe(to_df(res.data[t.key]), hide_index=True, width="stretch")
            for w in res.warnings:
                if w.startswith(t.key):
                    st.warning(w)
        except Exception as e:
            st.error(f"Förhandsgranskningen misslyckades: {e}")

    a, b, c3 = st.columns(3)
    with a.expander("➕ Lägg till kolumn"):
        with st.form(f"add_col_{t.key}", clear_on_submit=True):
            name = st.text_input("Kolumnnamn")
            type_raw = st.text_input("Datatyp", "nvarchar(100)", help="T.ex. int, bigint, decimal(18,2), nvarchar(50), date, datetime2, bit, uniqueidentifier")
            nullable = st.checkbox("Tillåt NULL", True)
            in_pk = st.checkbox("Ingår i primärnyckeln", False)
            if st.form_submit_button("Lägg till"):
                name = name.strip()
                if not name or t.column(name):
                    st.error("Ange ett kolumnnamn som inte redan finns.")
                else:
                    col = Column.from_type(name, type_raw.strip() or "nvarchar(100)", nullable=nullable and not in_pk, custom=True)
                    if col.kind == "other":
                        st.error(f"Okänd datatyp: {type_raw}")
                    else:
                        t.columns.append(col)
                        if in_pk:
                            t.primary_key.append(name)
                        col.generator, col.params, col.confidence, col.null_pct = infer_column(col, t, project)
                        select("cur_col", name)
                        changed()
                        st.rerun()
    with b.expander("🗑️ Ta bort kolumn"):
        if t.columns:
            victim = st.selectbox("Kolumn", [c.name for c in t.columns], key=f"del_col_{t.key}")
            st.caption("Kolumnen tas bort ur projektet (inte ur databasen). NOT NULL-kolumner utan standardvärde behöver finnas kvar för att laddningen ska fungera.")
            if st.button("Ta bort kolumnen"):
                edit.delete_column(project, t, victim)
                changed()
                st.rerun()
    with c3.expander("🔑 Primärnyckel"):
        names = [c.name for c in t.columns if not c.computed]
        pk = st.multiselect("Kolumner i primärnyckeln", names, default=[c for c in t.primary_key if c in names], key=f"pk_{t.key}_{ss.ver}")
        if pk != t.primary_key and st.button("Spara primärnyckel"):
            t.primary_key = pk
            for n in pk:
                t.column(n).nullable = False
            infer_table(t, project)
            changed()
            st.rerun()
    x, y = st.columns(2)
    with x.expander("🕓 Historik (SCD2)" + (" – på" if (t.history or {}).get("enabled") else "")):
        history_form(t)
    with y.expander("📌 Spara kolumnens inställning som regel för alla projekt"):
        rc = t.column(ss.get("cur_col") or "")
        if rc is None or rc.computed or t.fk_for(rc.name) or rc.generator not in REGISTRY:
            st.caption("Välj en kolumn som inte är en främmande nyckel under 'Anpassa kolumn'.")
        else:
            st.write(f"**{rc.name}** → {label_of(rc.generator)}")
            pattern = st.text_input("Gäller kolumner vars namn matchar", norm(rc.name).replace("_", ""), key=f"rule_pat_{t.key}_{rc.name}",
                                    help="Namn jämförs utan versaler, understreck och å/ä/ö. Använd * som jokertecken, t.ex. *kod eller avtal*.")
            same = st.checkbox(f"Bara kolumner med samma slags datatyp ({rc.kind})", True, key=f"rule_kind_{t.key}_{rc.name}")
            if st.button("Spara regel"):
                rules.add_rule(pattern.strip().lower(), rc.generator, rc.params, rc.kind if same else "", rc.null_pct)
                st.success(f"Regeln är sparad i {rules.rules_path()} och används när scheman läses in framöver.")


# ---------------------------------------------------------------- 5. Värdelistor

CODEBOOKS = {"Diagnoser (ICD-10-SE)": ("diagnosis", care.DIAGNOSES), "Åtgärder (KVÅ)": ("procedure", care.PROCEDURES),
             "Läkemedel (ATC)": ("drug", care.DRUGS)}


def tab_value_lists():
    st.write("Läs in textfiler med exempelvärden (ett värde per rad) eller CSV-filer med flera kolumner. Värdena sparas i projektet "
             "och kan användas av generatorn **Egna värden: Värdelista / exempelfil** – antingen som de är, eller som förlaga "
             "för nya värden med samma mönster. Använd bara påhittade eller avidentifierade exempel.")
    a, b = st.columns(2)
    with a:
        files = st.file_uploader("Text- eller CSV-filer", type=["txt", "csv", "tsv"], accept_multiple_files=True, key=f"vl_files_{ss.ver}")
        if files and st.button("Läs in filerna", type="primary"):
            n = 0
            for f in files:
                lists = valuelists.parse_file(f.name, f.getvalue())
                project.value_lists.update(lists)
                n += len(lists)
            changed()
            flash("success", f"{n} värdelistor inlästa.")
            st.rerun()
    with b:
        with st.form("paste_list", clear_on_submit=True):
            name = st.text_input("Namn på listan")
            text = st.text_area("Klistra in värden (ett per rad)", height=120)
            if st.form_submit_button("Spara listan"):
                vals = [v.strip() for v in text.splitlines() if v.strip()]
                if not name.strip() or not vals:
                    st.error("Ange både namn och värden.")
                else:
                    project.value_lists[name.strip()] = vals
                    changed()
                    st.rerun()

    if not project.value_lists:
        st.info("Inga värdelistor ännu.")
        return
    st.subheader("Inlästa listor")
    st.dataframe(pd.DataFrame([{
        "Lista": k, "Antal värden": len(v), "Unika": len(set(v)), "Exempel": ", ".join(v[:6]),
    } for k, v in project.value_lists.items()]), hide_index=True, width="stretch")
    st.caption("Listor från samma CSV-fil heter 'fil:kolumn'. Med inställningen 'Håll ihop rader från samma CSV-fil' hämtas värdena "
               "från samma exempelrad, så att t.ex. kod och benämning hör ihop.")

    a, b = st.columns(2)
    with a.expander("Använd en lista på en kolumn", expanded=True):
        if project.tables:
            lst = st.selectbox("Värdelista", list(project.value_lists), key="use_list")
            tkey = st.selectbox("Tabell", [t.key for t in project.tables], key="use_table")
            t = project.table(tkey)
            cname = st.selectbox("Kolumn", [c.name for c in t.columns if not c.computed], key=f"use_col_{tkey}")
            mode = st.selectbox("Läge", LIST_MODES, key="use_mode")
            linked = st.checkbox("Håll ihop rader från samma CSV-fil", ":" in lst, key="use_linked")
            if cname and st.button("Använd listan"):
                col = t.column(cname)
                col.generator, col.params, col.manual, col.confidence = "list", {"list": lst, "mode": mode, "linked": linked}, True, ""
                changed()
                flash("success", f"{tkey}.{cname} hämtar nu värden från '{lst}'.")
                st.rerun()
        else:
            st.caption("Lägg till tabeller först.")
    with b.expander("Testpersonnummer", expanded=bool(project.test_pnr_list)):
        st.caption("Välj en lista med officiella testpersonnummer (t.ex. Skatteverkets, nedladdade som fil). Då används bara de numren, "
                   "och födelsedatum och kön på raden följer numret. Inget nummer kan då sammanfalla med en verklig person. "
                   "Räcker listan inte till alla rader stannar genereringen vid listans längd för tabeller där personnumret är unikt.")
        opts = ["(ingen – generera påhittade nummer)"] + list(project.value_lists)
        cur = project.test_pnr_list if project.test_pnr_list in project.value_lists else opts[0]
        pickd = st.selectbox("Lista med testpersonnummer", opts, index=opts.index(cur), key=f"pnr_list_{ss.ver}")
        new = "" if pickd == opts[0] else pickd
        if new != project.test_pnr_list:
            project.test_pnr_list = new
            changed()
            st.rerun()
    with st.expander("Ta bort listor"):
        victims = st.multiselect("Listor", list(project.value_lists), key=f"del_lists_{ss.ver}")
        if victims and st.button("Ta bort valda"):
            for v in victims:
                project.value_lists.pop(v, None)
            if project.test_pnr_list in victims:
                project.test_pnr_list = ""
            changed()
            st.rerun()


def tab_codebooks():
    st.write("De inbyggda vårdkoderna är ett litet urval. Här läser du in hela kodverk från filer som ni har laddat ner, t.ex. "
             "Socialstyrelsens ICD-10-SE och KVÅ. De inbyggda vanliga koderna förblir vanliga i datan, medan resten av kodverket "
             "förekommer mer sällan. Kodtabeller får hela kodverket, en kod per rad.")
    rows = [{"Kodverk": label, "Inbyggda exempel": len(builtin), "Inlästa koder": len(project.codebooks.get(kind) or [])}
            for label, (kind, builtin) in CODEBOOKS.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    label = st.selectbox("Kodverk att läsa in", list(CODEBOOKS), key="cb_kind")
    kind = CODEBOOKS[label][0]
    f = st.file_uploader("Fil (Excel, CSV eller tabbseparerad text)", type=["xlsx", "csv", "tsv", "txt"], key=f"cb_file_{ss.ver}")
    if f is not None:
        try:
            if f.name.lower().endswith(".xlsx"):
                df = pd.read_excel(f, dtype=str)
            else:
                import io
                df = pd.read_csv(io.StringIO(valuelists.decode(f.getvalue())), sep=None, engine="python", dtype=str)
        except Exception as e:
            st.error(f"Kunde inte läsa filen: {e}")
            df = None
        if df is not None and len(df.columns):
            st.dataframe(df.head(8), hide_index=True, width="stretch")
            cols = list(df.columns)
            a, b = st.columns(2)
            code_col = a.selectbox("Kolumn med kod", cols, index=0, key="cb_code")
            text_col = b.selectbox("Kolumn med text", cols, index=min(1, len(cols) - 1), key="cb_text")
            if st.button("Läs in kodverket", type="primary"):
                pairs = [[str(c).strip(), "" if pd.isna(t) else str(t).strip()] for c, t in zip(df[code_col], df[text_col]) if not pd.isna(c) and str(c).strip()]
                project.codebooks[kind] = pairs
                for t in project.tables:  # kodtabeller ska rymma hela kodverket
                    if t.category == "reference" and any(c.generator.startswith("care.") for c in t.columns):
                        t.rows = default_rows(t, project)
                changed()
                flash("success", f"{len(pairs)} koder inlästa för {label}.")
                st.rerun()
    if project.codebooks.get(kind) and st.button(f"Ta bort inläst kodverk för {label}"):
        project.codebooks.pop(kind, None)
        changed()
        st.rerun()


def tab_profile():
    st.info("Har du själv åtkomst till produktionen? Använd **6. Generatorer → Lär från produktion** i stället: den analyserar direkt, "
            "spärrar personuppgifter och skapar generatorer. Skriptet här är till för när någon annan behöver köra analysen åt dig.")
    st.write("Få datan att likna produktion utan att någon rad lämnar den. Skriptet nedan returnerar **bara aggregat**: radantal, "
             "andel NULL, lägsta/högsta/medel för tal, första/sista datum och värdefördelning för kolumner med få unika värden. "
             "Identifierande kolumner (namn, personnummer, adress, fritext, nycklar) ingår inte, och sällsynta värden utelämnas.")
    if not project.tables:
        st.info("Läs in ett schema först.")
        return
    st.subheader("1. Skapa skriptet")
    a, b, _ = st.columns([1, 1, 2])
    max_distinct = int(a.number_input("Högst antal unika värden för värdefördelning", 2, 500, 50))
    min_count = int(b.number_input("Utelämna värden med färre förekomster än", 1, 1000, 5))
    sql = prodprofile.build_profile_sql(project, max_distinct, min_count)
    st.download_button("Ladda ner profil.sql", sql.encode("utf-8-sig"), file_name="profil.sql", mime="text/plain")
    with st.expander("Visa skriptet"):
        st.code(sql, language="sql")
    st.caption("Be någon med produktionsåtkomst granska och köra skriptet och spara resultatet som CSV med rubriker. "
               "Låt dem också titta igenom resultatet innan det lämnas över.")
    st.subheader("2. Läs in resultatet")
    f = st.file_uploader("Resultatfil (CSV)", type=["csv", "txt", "tsv"], key=f"prof_file_{ss.ver}")
    a, b, _ = st.columns([1.3, 1, 2])
    use_rows = a.checkbox("Använd produktionens radantal", True)
    factor = float(b.number_input("… multiplicerat med", 0.0001, 10.0, 0.01, format="%.4f", help="T.ex. 0,01 för en procent av produktionens storlek."))
    if f is not None and st.button("Tillämpa profilen", type="primary"):
        parsed = prodprofile.parse_profile(valuelists.decode(f.getvalue()))
        if not parsed:
            st.error("Filen innehåller inga rader i rätt format (tabell, kolumn, matt, varde, antal).")
        else:
            done = prodprofile.apply_profile(project, parsed, use_rows, factor)
            changed()
            flash("success", "Profilen är tillämpad: " + ", ".join(f"{n} {k}" for k, n in done.items() if n))
            st.rerun()


def tab_rules():
    st.write("Egna regler säger hur kolumner med ett visst namn alltid ska genereras, och gäller i alla projekt. De prövas före de "
             "inbyggda tolkningsreglerna när ett schema läses in. Nya regler skapar du under steg 4 → 'Spara kolumnens inställning som regel'.")
    st.caption(f"Reglerna sparas i `{rules.rules_path()}`. Filen kan delas i teamet; peka ut en gemensam fil med miljövariabeln DUMMYFILLER_RULES.")
    rs = rules.load_rules()
    if not rs:
        st.info("Inga egna regler ännu.")
        return
    st.dataframe(pd.DataFrame([{
        "Nr": i + 1, "Namnmönster": r["pattern"], "Datatyp": r.get("kind") or "alla", "Generator": label_of(r["generator"]),
        "Inställningar": ", ".join(f"{k}: {str(v).splitlines()[0][:30] if str(v) else ''}" for k, v in (r.get("params") or {}).items() if v not in ("", None))[:120],
    } for i, r in enumerate(rs)]), hide_index=True, width="stretch")
    a, b = st.columns(2)
    nr = int(a.number_input("Ta bort regel nr", 1, len(rs), 1))
    if a.button("Ta bort regeln"):
        rules.delete_rule(nr - 1)
        st.rerun()
    if b.button("Tillämpa reglerna på projektet nu", help="Kolumner som du har anpassat för hand lämnas orörda."):
        for t in project.tables:
            infer_table(t, project)
        changed()
        st.rerun()


def page_lists():
    st.header("5. Värdelistor – styr datan med egna exempel")
    t1, t2, t3 = st.tabs(["Värdelistor", "Kodverk (vård)", "Profil från produktion"])
    with t1:
        tab_value_lists()
    with t2:
        tab_codebooks()
    with t3:
        tab_profile()
    st.caption("Egna generatorer, regionens egna koder och regler för kolumnnamn hanterar du under **6. Generatorer**.")


# ---------------------------------------------------------------- 6. Generatorer

KIND_LABELS = {"table": "Uppslagstabell (värden som hör ihop radvis)", "preset": "Förinställning av en befintlig generator"}
NO_WEIGHT = "(ingen – alla rader lika vanliga)"
NEW_GEN = "__ny__"


def df_rows(df: pd.DataFrame) -> list[list]:
    """Rader från en tabell som vanliga Python-värden (tomma celler blir None)."""
    out = []
    for r in df.itertuples(index=False):
        row = []
        for v in r:
            if v is None or (not isinstance(v, (list, str)) and pd.isna(v)):
                row.append(None)
            else:
                row.append(v.item() if hasattr(v, "item") else v)
        out.append(row)
    return out


def read_table(name: str, raw: bytes | str) -> pd.DataFrame:
    """CSV, tabbseparerad text (t.ex. inklistrad från Excel) eller Excel-fil till en tabell med texter."""
    import io
    if name.lower().endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(raw), dtype=str).fillna("")
    text = valuelists.decode(raw) if isinstance(raw, bytes) else raw
    return pd.read_csv(io.StringIO(text.strip()), sep=None, engine="python", dtype=str).fillna("")


def new_draft() -> dict:
    return {"key": None, "name": "", "kind": "table", "description": "", "columns": ["Kod", "Benämning", "Vikt"], "weight": "Vikt",
            "rows": [["", "", 1]], "base": "pattern", "params": {}}


def preset_params(spec, cur: dict, kp: str) -> dict:
    """Formulär för en förinställnings parametrar. Parametrar som beror på tabellen ställs in per kolumn."""
    out = {}
    skipped = []
    for p in spec.params:
        v = cur.get(p.name, p.default)
        k, h = f"{kp}_{p.name}", p.help or None
        if p.type in library.CONTEXT_TYPES or p.name == "group":
            skipped.append(p.label)
        elif p.type == "int":
            out[p.name] = int(st.number_input(p.label, value=int(v), step=1, key=k, help=h))
        elif p.type == "float":
            out[p.name] = float(st.number_input(p.label, value=float(v), key=k, help=h))
        elif p.type == "bool":
            out[p.name] = st.checkbox(p.label, bool(v), key=k, help=h)
        elif p.type == "select":
            opts = list(p.options or [])
            out[p.name] = st.selectbox(p.label, opts, index=opts.index(v) if v in opts else 0, key=k, help=h)
        elif p.type == "text":
            out[p.name] = st.text_area(p.label, str(v), height=150, key=k, help=h)
        else:
            out[p.name] = st.text_input(p.label, str(v), key=k, help=h)
    if skipped:
        st.caption("Ställs in per kolumn: " + ", ".join(skipped) + ".")
    return out


def gen_editor(sel: str):
    gens = library.custom_generators()
    if ss.get("lib_draft_for") != sel:
        ss.lib_draft = copy.deepcopy(gens[sel]) if sel in gens else new_draft()
        ss.lib_draft_for = sel
        ss.lib_dv = ss.get("lib_dv", 0) + 1
    d = ss.lib_draft
    kp = f"lib_{sel}_{ss.lib_dv}"
    d["name"] = st.text_input("Namn", d["name"], key=f"{kp}_name", placeholder="t.ex. JH: Ansvar",
                              help="Visas i generatorlistan under 'Egna'. Börja gärna med JH: så att regionens generatorer hålls ihop.")
    d["description"] = st.text_input("Beskrivning (valfri)", d.get("description") or "", key=f"{kp}_desc")
    kinds = list(KIND_LABELS)
    d["kind"] = st.radio("Slag", kinds, index=kinds.index(d.get("kind", "table")), format_func=KIND_LABELS.get, key=f"{kp}_kind", horizontal=True)

    edited = None
    if d["kind"] == "table":
        st.caption("Varje rad är en uppsättning värden som hör ihop, t.ex. ansvarskod, benämning och förvaltning. En kolumn som använder "
                   "generatorn väljer ett fält; kolumner på samma rad får värden från samma tabellrad. En viktkolumn styr hur vanlig varje rad är.")
        with st.expander("📥 Läs in från fil eller klistra in", expanded=not any(any(v not in (None, "", 1) for v in r) for r in d["rows"])):
            f = st.file_uploader("CSV-, text- eller Excel-fil", type=["csv", "txt", "tsv", "xlsx"], key=f"{kp}_file")
            pasted = st.text_area("… eller klistra in (CSV, eller kopierat direkt från Excel)", key=f"{kp}_paste", height=110,
                                  placeholder="Kod;Benämning;Förvaltning\n11000;Ekonomienheten;Regionstaben")
            if st.button("Använd som tabell", key=f"{kp}_load"):
                try:
                    df = read_table(f.name, f.getvalue()) if f is not None else read_table("inklistrat.csv", pasted)
                    if df.empty or not len(df.columns):
                        raise ValueError("hittade inga rader")
                    d["columns"] = [str(c).strip() for c in df.columns]
                    d["rows"] = df_rows(df)
                    d["weight"] = next((c for c in d["columns"] if c.lower() in ("vikt", "weight", "andel")), "")
                    ss.lib_dv += 1
                    st.rerun()
                except Exception as e:
                    st.error(f"Kunde inte läsa tabellen: {e}")
        base = pd.DataFrame(d["rows"], columns=d["columns"]) if d["columns"] else pd.DataFrame()
        edited = st.data_editor(base, num_rows="dynamic", hide_index=True, width="stretch", key=f"{kp}_tbl")
        a, b, c = st.columns([1.2, 0.8, 1.6])
        newcol = a.text_input("Ny kolumn", key=f"{kp}_newcol", placeholder="Kolumnnamn", label_visibility="collapsed")
        if b.button("➕ Kolumn", key=f"{kp}_addcol") and newcol.strip() and newcol.strip() not in d["columns"]:
            d["rows"] = [r + [None] for r in df_rows(edited)]
            d["columns"] = list(edited.columns) + [newcol.strip()]
            ss.lib_dv += 1
            st.rerun()
        drop = c.selectbox("Ta bort kolumn", ["(ta bort kolumn …)"] + list(edited.columns), key=f"{kp}_dropcol", label_visibility="collapsed")
        if drop != "(ta bort kolumn …)":
            i = list(edited.columns).index(drop)
            d["rows"] = [r[:i] + r[i + 1:] for r in df_rows(edited)]
            d["columns"] = [x for x in edited.columns if x != drop]
            d["weight"] = "" if d.get("weight") == drop else d.get("weight")
            ss.lib_dv += 1
            st.rerun()
        wopts = [NO_WEIGHT] + list(edited.columns)
        w = st.selectbox("Viktkolumn", wopts, index=wopts.index(d["weight"]) if d.get("weight") in wopts else 0, key=f"{kp}_weight",
                         help="Tal som anger hur vanlig raden är. Vikt 0 betyder att raden bara används i kodtabeller.")
        d["weight"] = "" if w == NO_WEIGHT else w
        current = {**d, "columns": [str(x) for x in edited.columns], "rows": df_rows(edited)}
    else:
        bases = [k for k in REGISTRY if not k.startswith(library.PREFIX) and k not in ("null",)]
        blabels = [label_of(k) for k in bases]
        cur = d.get("base") if d.get("base") in bases else "pattern"
        picked = st.selectbox("Bygger på", blabels, index=blabels.index(label_of(cur)), key=f"{kp}_base",
                              help="Välj den generator som ska förinställas. Inställningarna nedan sparas i den egna generatorn.")
        base = bases[blabels.index(picked)]
        if base != d.get("base"):
            d["base"], d["params"] = base, {}
        spec = REGISTRY[base]
        if spec.help:
            st.caption(spec.help)
        d["params"] = preset_params(spec, {**defaults(base), **(d.get("params") or {})}, f"{kp}_{base}")
        current = dict(d)

    st.markdown("**Förhandsgranskning**")
    try:
        cols, rows, warns = library.preview(current, 8, project.locale)
        if cols:
            st.dataframe(pd.DataFrame([[str(v) if v is not None else None for v in r] for r in rows], columns=cols), hide_index=True, width="stretch")
        for w in warns:
            st.warning(w)
    except Exception as e:
        st.error(f"Förhandsgranskningen misslyckades: {e}")

    fields = library.table_fields(current) if current["kind"] == "table" else []
    with st.expander("📌 Använd automatiskt för kolumner med visst namn"):
        st.caption("Skapar en regel: när ett schema läses in får kolumner vars namn matchar mönstret den här generatorn. "
                   "Namn jämförs utan versaler, understreck och å/ä/ö; * är jokertecken, t.ex. *ansvar eller kst*.")
        pattern = st.text_input("Namnmönster", key=f"{kp}_rule", placeholder="t.ex. *ansvar")
        rule_field = st.selectbox("Fält", fields, key=f"{kp}_rulefield") if fields else None

    a, b, _ = st.columns([1, 1, 2])
    if a.button("💾 Spara generatorn", type="primary", key=f"{kp}_save"):
        try:
            if not current["name"].strip():
                raise ValueError("Ge generatorn ett namn.")
            if current["kind"] == "table":
                if not fields:
                    raise ValueError("Tabellen behöver minst en kolumn utöver viktkolumnen.")
                if not any(any(v is not None and str(v).strip() for v in r) for r in current["rows"]):
                    raise ValueError("Tabellen behöver minst en rad.")
                current = {k: current[k] for k in ("key", "name", "kind", "description", "columns", "weight", "rows")}
            else:
                current = {k: current[k] for k in ("key", "name", "kind", "description", "base", "params")}
            current["name"] = current["name"].strip()
            if not current.get("key"):
                current["key"] = library.new_key(current["name"], set(REGISTRY) | set(library.custom_generators()))
            library.save_generator(current)
            if pattern.strip():
                rules.add_rule(pattern.strip().lower(), current["key"], {"field": rule_field} if rule_field else {})
            ss.lib_draft_for = None
            select("lib_cur", current["key"])
            flash("success", f"Generatorn '{current['name']}' är sparad och finns nu i generatorlistan under 'Egna'.")
            changed()
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if sel in gens:
        used = library.usage(project, sel)
        with b.popover("🗑️ Ta bort"):
            st.caption((f"Används av {len(used)} kolumner i det här projektet. De fortsätter att fungera med projektets kopia av generatorn. "
                        if used else "") + "Generatorn tas bort ur biblioteket.")
            if st.button("Ta bort generatorn", key=f"{kp}_del"):
                library.delete_generator(sel)
                ss.lib_draft_for = None
                select("lib_cur", NEW_GEN)
                changed()
                st.rerun()
        with st.expander("🎯 Använd på en kolumn i projektet"):
            if not project.tables:
                st.caption("Projektet har inga tabeller ännu.")
            else:
                tkey = st.selectbox("Tabell", [t.key for t in project.tables], key=f"{kp}_use_t")
                tt = project.table(tkey)
                cname = st.selectbox("Kolumn", [c.name for c in tt.columns if not c.computed], key=f"{kp}_use_c_{tkey}")
                ufield = st.selectbox("Fält", fields, key=f"{kp}_use_f") if fields else None
                if cname and st.button("Använd", key=f"{kp}_use"):
                    col = tt.column(cname)
                    col.generator, col.params = sel, ({"field": ufield} if ufield else {})
                    col.manual, col.confidence = True, ""
                    changed()
                    flash("success", f"{tt.name}.{cname} använder nu '{gens[sel]['name']}'.")
                    st.rerun()


def tab_custom_generators():
    gens = library.custom_generators()
    left, right = st.columns([1, 2.4], gap="large")
    with left:
        st.write("Bygg egna generatorer av regionens egna koder och mönster. De blir gemensamma för alla projekt och visas i "
                 "generatorlistan under **Egna**.")
        options = [NEW_GEN] + sorted(gens, key=lambda k: gens[k]["name"].lower())
        cur = ss.get("lib_cur") if ss.get("lib_cur") in options else NEW_GEN
        sel = st.radio("Generatorer", options, index=options.index(cur), key=f"lib_pick_{ss.get('pickver_lib_cur', 0)}",
                       format_func=lambda k: "➕ Ny generator" if k == NEW_GEN else gens[k]["name"], label_visibility="collapsed")
        ss.lib_cur = sel
        if gens:
            st.caption(" · ".join(f"{gens[k]['name']}: {len(library.usage(project, k))} kolumner" for k in options[1:])
                       + " i det här projektet")
        missing = sorted({c.generator for t in project.tables for c in t.columns if c.generator.startswith(library.PREFIX) and library.origin(c.generator)})
        if missing:
            st.warning("Projektet använder egna generatorer som saknas i ditt bibliotek (de fungerar ändå tack vare projektets kopia): "
                       + ", ".join(REGISTRY[k].label if k in REGISTRY else k for k in missing))
            if st.button("Lägg till dem i mitt bibliotek"):
                for k in missing:
                    if k in (project.custom_generators or {}):
                        library.save_generator(project.custom_generators[k])
                changed()
                st.rerun()
    with right:
        gen_editor(sel)


def tab_builtin_lists():
    st.write("De inbyggda listorna är påhittade exempel. Här ersätter du dem med regionens riktiga koder och nivåer – ändringen gäller "
             "i alla projekt och för alla generatorer som använder listan.")
    keys = [s.key for s in library.LIST_SPECS]
    groups = list(dict.fromkeys(s.group for s in library.LIST_SPECS))
    a, b = st.columns([1, 2])
    group = a.selectbox("Område", groups, key="blt_group")
    in_group = [k for k in keys if library.SPECS[k].group == group]
    key = b.selectbox("Lista", in_group, key=f"blt_list_{group}",
                      format_func=lambda k: library.SPECS[k].label + ("  · ändrad" if library.is_overridden(k) else ""))
    spec = library.SPECS[key]
    if spec.help:
        st.caption(spec.help)
    rows = library.current_rows(key)
    st.caption(f"{len(rows)} rader" + (f" (originalet har {len(library.original_rows(key))})" if library.is_overridden(key) else " · original"))
    bv = ss.get("blt_v", 0)
    edited = st.data_editor(pd.DataFrame(rows, columns=[c for c, _ in spec.columns]), num_rows="dynamic", hide_index=True, width="stretch",
                            key=f"blt_{key}_{bv}_{ss.ver}")
    c1, c2, c3 = st.columns([1, 1, 1.4])
    if c1.button("💾 Spara ändringarna", type="primary", key=f"blt_save_{key}"):
        try:
            library.save_list(key, df_rows(edited))
            ss.blt_v = bv + 1
            changed()
            flash("success", f"'{spec.label}' är sparad.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if library.is_overridden(key) and c2.button("↩️ Återställ originalet", key=f"blt_reset_{key}"):
        library.reset_list(key)
        ss.blt_v = bv + 1
        changed()
        st.rerun()
    c3.download_button("Ladda ner som CSV", edited.to_csv(sep=";", index=False).encode("utf-8-sig"), file_name=f"{spec.label}.csv",
                       mime="text/csv", key=f"blt_dl_{key}")
    with st.expander("📥 Ersätt med innehållet i en fil"):
        st.caption("Kolumnerna läses i ordning: " + ", ".join(c for c, _ in spec.columns) + ". Första raden ska vara rubriker.")
        f = st.file_uploader("CSV- eller Excel-fil", type=["csv", "txt", "tsv", "xlsx"], key=f"blt_file_{key}_{bv}")
        if f is not None and st.button("Ersätt listan", key=f"blt_load_{key}"):
            try:
                df = read_table(f.name, f.getvalue())
                library.save_list(key, df_rows(df.iloc[:, :len(spec.columns)]))
                ss.blt_v = bv + 1
                changed()
                flash("success", f"'{spec.label}' har ersatts med {len(df)} rader från {f.name}.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte läsa filen: {e}")


def tab_share():
    st.write("Exportera biblioteket – egna generatorer, ändrade listor och egna regler – till en fil som teamet kan dela, t.ex. i ett "
             "gemensamt git-repo. Den som läser in filen får samma generatorer.")
    include = st.checkbox("Ta med egna regler", True)
    text = library.export_yaml(include)
    a, b = st.columns(2)
    with a:
        st.download_button("⬇️ Ladda ner biblioteket (YAML)", text.encode("utf-8"), file_name="dummyfiller_bibliotek.yaml", mime="text/yaml")
        path = st.text_input("… eller spara till fil", "bibliotek/dummyfiller_bibliotek.yaml")
        if st.button("Spara till filen"):
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(text, encoding="utf-8")
                st.success(f"Sparat till {Path(path).resolve()}")
            except Exception as e:
                st.error(f"Kunde inte spara: {e}")
    with b:
        f = st.file_uploader("Läs in ett bibliotek", type=["yaml", "yml"], key=f"lib_import_{ss.ver}")
        if f is not None and st.button("Läs in", type="primary"):
            try:
                n = library.import_yaml(valuelists.decode(f.getvalue()), include)
                changed()
                flash("success", "Inläst: " + ", ".join(f"{v} {k}" for k, v in n.items()) + ". Generatorer och listor med samma namn har ersatts.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte läsa biblioteket: {e}")
    st.caption("Från kommandoraden: `python -m dummyfiller import-bibliotek fil.yaml` läser in, och "
               "`python -m dummyfiller generate projekt.yaml --bibliotek fil.yaml` använder filen utan att ändra det lokala biblioteket.")


PROTECTION_TEXT = """
- **Bara aggregat sparas.** Ett slumpvist urval läses in i minnet under analysen och slängs när tabellen är klar. Det som
  sparas är fördelningar, intervall, mönster och – för kodtabeller – koderna.
- **Hård spärr.** Personnummer och samordningsnummer, namn, användarnamn, e-post, telefonnummer, gatuadresser, bankkonton och
  fritext spärras – både efter kolumnens namn och efter innehållet, så att en kolumn med ett oskyldigt namn ändå fångas.
  Spärrade kolumner kan inte väljas, och spärren går inte att stänga av.
- **Även enskilda värden** som ser ut som personuppgifter tas bort ur tillåtna kolumner.
- **Födelsedatum** är skyddade: bara åldersintervallet (P1–P99) lärs.
- **Små grupper utelämnas:** värden som förekommer färre än k gånger tas aldrig med (k är minst 5). Extremvärden skärs bort.
- **Logg:** varje analys loggas med vem, när, vilken databas och vilka kolumner som lärdes eller spärrades.
- Anslutningen öppnas med läsavsikt (ApplicationIntent=ReadOnly) och lösenordet sparas inte.
"""
LEARN_KIND = {"choice": "Värden med vikt", "bool": "Andel sant", "histogram": "Talfördelning", "date": "Säsongsprofil",
              "pattern": "Mönster", "conditional": "Beroende värden", "birth": "Åldersintervall", "codetable": "Kodtabell"}


def prod_engine():
    c = ss.prod_conn
    if c["mode"] == "SQL Server":
        if not c["server"] or not c["database"]:
            raise RuntimeError("Ange server och databas för produktionen.")
        url = dbio.build_url(c["server"], c["database"], c["auth"], c["user"], ss.get("prod_pw", ""),
                             c["driver"] or (dbio.list_drivers() or ["ODBC Driver 18 for SQL Server"])[0], c["encrypt"], c["trust"], read_only=True)
    else:
        if not c["url"]:
            raise RuntimeError("Ange en SQLAlchemy-URL.")
        url = c["url"]
    return dbio.make_engine(url)


_mapper = components.declare_component("dummyfiller_mapper", path=str(Path(__file__).resolve().parent / "mapper"))


def handle_map_event(ev: dict, mode: str) -> None:
    m = project.prod_mapping
    schema = ss.get("prod_schema") or []
    kind = ev.get("type")
    if mode == "tables":
        if kind == "select":
            ss.map_sel = ev.get("l")
        elif kind == "link" and any(matching.prod_key(p) == ev.get("r") for p in schema) and project.table(ev.get("l", "")):
            matching.link_table(project, m, schema, ev["l"], ev["r"])
            ss.map_sel = ev["l"]
        elif kind == "unlink":
            matching.link_table(project, m, schema, ev["l"], None)
    elif ss.get("map_sel"):
        if kind == "link":
            matching.link_column(m, ss.map_sel, ev["l"], ev["r"])
        elif kind == "unlink":
            matching.link_column(m, ss.map_sel, ev["l"], None)


def learn_matching(keys: list[str]) -> dict | None:
    """Steg 2: matcha projektets tabeller och kolumner mot produktionens. Returnerar kopplingen, eller None (samma namn)."""
    st.markdown("**2. Matcha projektet mot produktionen**")
    for cmp_key, seq_key, mode in (("map_tables_cmp", "map_seq_t", "tables"), ("map_cols_cmp", "map_seq_c", "columns")):
        ev = ss.get(cmp_key)  # händelsen från matchningsvyn som startade den här körningen
        if isinstance(ev, dict) and ev.get("seq") != ss.get(seq_key):
            ss[seq_key] = ev.get("seq")
            if ss.get("prod_schema") is not None:
                handle_map_event(ev, mode)
    a, b, c, _ = st.columns([1.5, 1.3, 0.9, 2])
    if a.button("🔗 Hämta produktionens schema", help="Läser bara metadata: tabeller, vyer, kolumner och datatyper. Ingen data."):
        try:
            with st.spinner("Läser produktionens schema …"):
                ss.prod_schema = dbio.list_tables(prod_engine())
            project.prod_mapping = matching.auto_match(project, ss.prod_schema, project.prod_mapping)
            ss.map_sel = next((k2 for k2 in keys if k2 in project.prod_mapping["tables"]), None)
        except Exception as e:
            st.error(f"Kunde inte läsa schemat: {e}")
    schema = ss.get("prod_schema")
    saved = project.prod_mapping if (project.prod_mapping or {}).get("tables") else None
    if schema is None:
        if saved:
            st.caption(f"Projektets sparade matchning används ({len(saved['tables'])} tabeller). Hämta produktionens schema för att se och ändra den.")
        else:
            st.caption("Hämta produktionens schema för att matcha tabeller och kolumner som heter olika i projektet och i produktionen. "
                       "Utan matchning letas de upp med samma namn som i projektet.")
        return saved
    if b.button("✨ Matcha automatiskt", help="Matchar det som inte är kopplat för hand. Dina manuella kopplingar behålls."):
        project.prod_mapping = matching.auto_match(project, schema, project.prod_mapping)
    if c.button("Börja om", help="Tar bort alla kopplingar, även manuella, och matchar automatiskt på nytt."):
        project.prod_mapping = matching.auto_match(project, schema, None, reset=True)
    m = project.prod_mapping
    m.setdefault("tables", {})
    m.setdefault("columns", {})
    by_key = {matching.prod_key(p): p for p in schema}
    s = matching.summary(project, m, keys)
    st.caption(f"{s['tabeller']} av {s['av']} tabeller matchade · {s['omatchade kolumner']} kolumner utan motsvarighet · "
               f"{len(schema)} tabeller och vyer i produktionen. Dra från pricken vid en tabell till en tabell på andra sidan – eller "
               "klicka på en på varje sida – för att koppla. Klicka på en linje för att ta bort kopplingen.")

    left = []
    for key in keys:
        t = project.table(key)
        tm = m["tables"].get(key)
        ncols = len([x for x in t.columns if not x.computed])
        nm = len(m["columns"].get(key, {})) if tm else 0
        left.append({"id": key, "label": t.name, "sub": (f"{t.schema} · " if t.schema else "") + f"{ncols} kolumner",
                     "note": f"{nm}/{ncols} kolumner" if tm else "ej matchad", "warn": not tm or nm < ncols})
    right = [{"id": matching.prod_key(p), "label": p["name"],
              "sub": (f"{p['schema']} · " if p["schema"] else "") + f"{len(p['columns'])} kolumner" + (" · vy" if p.get("view") else "")}
             for p in sorted(schema, key=lambda p: (p["schema"], p["name"].lower()))]
    links = [{"l": k2, "r": matching.prod_key(v), "kind": v["kind"], "score": v.get("score", 1)}
             for k2, v in m["tables"].items() if k2 in keys and matching.prod_key(v) in by_key]
    _mapper(left=left, right=right, links=links, selected=ss.get("map_sel"), leftTitle="Projektet", rightTitle="Produktionen",
            mode="tables", height=min(560, 100 + 40 * max(len(left), min(len(right), 12))), key="map_tables_cmp", default=None)

    sel = ss.get("map_sel")
    tm = m["tables"].get(sel) if sel else None
    if sel and tm and matching.prod_key(tm) in by_key:
        t, p = project.table(sel), by_key[matching.prod_key(tm)]
        st.markdown(f"**Kolumner:** {t.name} ↔ {matching.prod_key(tm)}")
        cm = m["columns"].get(sel, {})
        prod_cols = {x["name"]: x for x in p["columns"]}
        cleft = [{"id": x.name, "label": x.name, "sub": x.type_raw + ("" if x.nullable else " NOT NULL"),
                  "note": "" if x.name in cm else "ingen motsvarighet", "warn": x.name not in cm} for x in t.columns if not x.computed]
        cright = [{"id": x["name"], "label": x["name"], "sub": x["type"]} for x in p["columns"]]
        clinks = [{"l": a2, "r": v["name"], "kind": v["kind"], "score": v.get("score", 1),
                   "mismatch": matching.type_mismatch(t.column(a2), prod_cols[v["name"]]["kind"])}
                  for a2, v in cm.items() if t.column(a2) is not None and v["name"] in prod_cols]
        _mapper(left=cleft, right=cright, links=clinks, selected=None, leftTitle=t.name, rightTitle=p["name"], mode="columns",
                height=min(640, 100 + 40 * max(len(cleft), min(len(cright), 14))), key="map_cols_cmp", default=None)
        st.caption("Röd streckad linje: olika slags datatyp – värdena tolkas då som projektets typ. Kolumner utan motsvarighet hoppas över i analysen. "
                   "Spärren för personuppgifter prövar både projektets och produktionens kolumnnamn.")
    elif sel:
        st.caption(f"Koppla {project.table(sel).name} till en tabell i produktionen för att matcha kolumnerna.")
    else:
        st.caption("Klicka på en tabell till vänster för att se och matcha dess kolumner.")
    return m


def tab_learn():
    ss.setdefault("prod_conn", {"mode": "SQL Server", "server": "", "database": "", "auth": dbio.AUTH_MODES[0], "user": "", "driver": "",
                                "encrypt": True, "trust": True, "url": ""})
    st.write("Skapa generatorer utifrån **produktionsdata**, utan att några personuppgifter följer med. Kör analysen på en dator där du "
             "har behörighet till produktionsdata; resultatet – bara aggregat – kan sedan delas med utvecklarna via biblioteket.")
    with st.expander("🛡️ Så skyddas personuppgifterna"):
        st.markdown(PROTECTION_TEXT)
        st.caption("Verktyget minskar risken men ersätter inte er egen bedömning. Stäm gärna av upplägget med dataskyddsombudet.")
    res = ss.get("learn_result")
    with st.expander("1. Anslutning till produktion", expanded=res is None):
        c = ss.prod_conn
        c["mode"] = st.radio("Anslutning", ["SQL Server", "Egen SQLAlchemy-URL"], index=0 if c["mode"] == "SQL Server" else 1, horizontal=True, key="prod_mode")
        if c["mode"] == "SQL Server":
            a, b = st.columns(2)
            c["server"] = a.text_input("Server", c["server"], key="prod_server")
            c["database"] = b.text_input("Databas", c["database"], key="prod_db")
            c["auth"] = a.selectbox("Inloggning", dbio.AUTH_MODES, index=dbio.AUTH_MODES.index(c["auth"]), key="prod_auth")
            drivers = dbio.list_drivers() or ["ODBC Driver 18 for SQL Server"]
            c["driver"] = b.selectbox("ODBC-drivrutin", drivers, index=drivers.index(c["driver"]) if c["driver"] in drivers else 0, key="prod_driver")
            if c["auth"] != dbio.AUTH_MODES[0]:
                c["user"] = a.text_input("Användare", c["user"], key="prod_user")
            if c["auth"] == dbio.AUTH_MODES[1]:
                ss.prod_pw = b.text_input("Lösenord", ss.get("prod_pw", ""), type="password", key="prod_pw_input")
            c["encrypt"] = a.checkbox("Kryptera anslutningen", c["encrypt"], key="prod_enc")
            c["trust"] = b.checkbox("Lita på serverns certifikat", c["trust"], key="prod_trust")
        else:
            c["url"] = st.text_input("SQLAlchemy-URL", c["url"], key="prod_url")
        st.caption("Anslutningen sparas inte i projektet. Det räcker med läsbehörighet.")

    if not project.tables:
        st.info("Läs in schemat först (steg 1). Analysen använder projektets tabeller och letar upp motsvarande tabeller i produktionen.")
        return
    keys = [t.key for t in project.tables]
    mapping = learn_matching(keys)
    st.markdown("**3. Vad ska läras?**")
    default = [t.key for t in project.tables if t.include and (mapping is None or t.key in (mapping.get("tables") or {}))]
    sel = st.multiselect("Tabeller", keys, default=default, key="learn_tables",
                         help="Tabeller som inte är matchade mot produktionen hoppas över." if mapping is not None else None)
    a, b, _ = st.columns([1, 1, 2])
    k = int(a.number_input("Minsta antal förekomster (k)", learn.K_MIN, 1000, 10, key="learn_k",
                           help=f"Värden som förekommer färre gånger än så här tas aldrig med. Kan inte sättas lägre än {learn.K_MIN}."))
    n = int(b.number_input("Urval per tabell (rader)", learn.CODE_TABLE_MAX, 1_000_000, 50_000, step=10_000, key="learn_sample",
                           help="Ett slumpvist urval läses in i minnet under analysen och slängs sedan."))
    if st.button("🔍 Analysera produktionsdata", type="primary", disabled=not sel):
        bar = st.progress(0.0, "Analyserar …")
        try:
            c = ss.prod_conn
            source = f"{c['server']}/{c['database']}" if c["mode"] == "SQL Server" else c["url"].split("@")[-1].split("///")[-1]
            ss.learn_result = learn.analyse(prod_engine(), project, sel, k, n, source=source, mapping=mapping,
                                            progress=lambda key, i, total: bar.progress(i / max(total, 1), f"Analyserar {key} …"))
            ss.learn_v = ss.get("learn_v", 0) + 1
        except Exception as e:
            st.error(f"Analysen misslyckades: {e}")
        bar.empty()
        res = ss.get("learn_result")

    if res is not None:
        st.markdown("**4. Granska och skapa generatorer**")
        st.caption(f"Analys av {res.meta.get('source')} {res.meta.get('at', '').replace('T', ' ')} · k = {res.meta.get('k')} · av {res.meta.get('user')}")
        for tr in res.tables:
            if tr.error:
                st.warning(f"{tr.table}: {tr.error}")
        learned = [f for f in res.findings if f.status == learn.LEARNED]
        blocked = [f for f in res.findings if f.status in (learn.BLOCKED, learn.PROTECTED) and f.kind != "birth"]
        skipped = [f for f in res.findings if f.status == learn.SKIPPED]
        m1, m2, m3 = st.columns(3)
        m1.metric("Kolumner som kan läras", len(learned))
        m2.metric("🔒 Spärrade", len(blocked))
        m3.metric("Hoppas över", len(skipped))
        if learned:
            df = pd.DataFrame([{"Använd": True, "Tabell": f.table, "Kolumn": f.column, "Slag": LEARN_KIND.get(f.kind, f.kind),
                                "Det här lärs": f.summary + (f" · {f.reason}" if f.reason else ""),
                                "Andel NULL %": f.null_pct} for f in learned])
            edited = st.data_editor(df, hide_index=True, width="stretch", key=f"learn_pick_{ss.get('learn_v', 0)}",
                                    disabled=["Tabell", "Kolumn", "Slag", "Det här lärs", "Andel NULL %"],
                                    column_config={"Det här lärs": st.column_config.TextColumn(width="large")})
        if blocked:
            st.markdown("**🔒 Spärrade kolumner** – lärs inte och kan inte väljas")
            st.dataframe(pd.DataFrame([{"Tabell": f.table, "Kolumn": f.column, "Skäl": f.reason} for f in blocked]), hide_index=True, width="stretch")
        if skipped:
            with st.expander(f"Kolumner som hoppas över ({len(skipped)})"):
                st.dataframe(pd.DataFrame([{"Tabell": f.table, "Kolumn": f.column, "Skäl": f.reason} for f in skipped]), hide_index=True, width="stretch")
        structure = [{"Tabell": tr.table, "Rader i produktion": tr.rows, "Urval": tr.sampled,
                      "Barn per förälder": " · ".join(f"{fo['column']} → {fo['parent']}: {fo['summary']}" for fo in tr.fanout)}
                     for tr in res.tables if not tr.error]
        if structure:
            with st.expander("Radantal och relationer"):
                st.dataframe(pd.DataFrame(structure), hide_index=True, width="stretch")
        if learned:
            a, b = st.columns(2)
            to_library = a.checkbox("Spara som egna generatorer i biblioteket", True, key="learn_lib",
                                    help="Generatorerna heter 'Lärd: Tabell.Kolumn' och kan delas med teamet. Annars sparas de bara i projektet.")
            to_project = a.checkbox("Använd dem på projektets kolumner", True, key="learn_proj")
            rows_mode = b.radio("Radantal", ["Behåll projektets radantal", "Produktionens radantal ×"], key="learn_rows_mode")
            factor = float(b.number_input("Faktor", 0.0001, 10.0, 0.01, format="%.4f", key="learn_factor",
                                          help="T.ex. 0,01 för en procent av produktionens storlek. Kodtabeller får alltid alla rader.")) if rows_mode != "Behåll projektets radantal" else None
            fanout = b.checkbox("Använd produktionens antal barn per förälder", True, key="learn_fanout")
            if st.button("✅ Skapa generatorer", type="primary"):
                chosen = {(r["Tabell"], r["Kolumn"]) for r in edited.to_dict("records") if r["Använd"]}
                done = learn.apply(res, project, chosen, to_library, to_project, factor, fanout)
                changed()
                flash("success", "Klart: " + ", ".join(f"{v} {k}" for k, v in done.items() if v) + ".")
                st.rerun()
        if st.button("Släng analysresultatet"):
            ss.learn_result = None
            st.rerun()

    with st.expander("📜 Logg över analyser av produktionsdata"):
        log = store.audit_list()
        if not log:
            st.caption("Inga analyser ännu.")
        else:
            st.dataframe(pd.DataFrame([{"Tid": e["at"].replace("T", " "), "Användare": e.get("user"), "Källa": e.get("source"), "k": e.get("k"),
                                        "Tabeller": len(e.get("tabeller") or []), "Lärda kolumner": len(e.get("lärs") or []),
                                        "Spärrade": len(e.get("spärrade") or {}), "Generatorer skapade": len(e.get("generatorer") or [])}
                                       for e in log]), hide_index=True, width="stretch")


def page_generators():
    st.header("6. Generatorer – bygg och anpassa")
    t1, t2, t3, t4, t5 = st.tabs(["Egna generatorer", "Lär från produktion", "Inbyggda listor", "Regler", "Dela med teamet"])
    with t1:
        tab_custom_generators()
    with t2:
        tab_learn()
    with t3:
        tab_builtin_lists()
    with t4:
        tab_rules()
    with t5:
        tab_share()


# ---------------------------------------------------------------- 7. Generera

LOCALES = ["sv_SE", "en_US", "en_GB", "nb_NO", "da_DK", "fi_FI", "de_DE"]
MODES = ["Ny datamängd", "Lägg till ny data ovanpå befintlig (inkrementellt)"]


def page_generate():
    st.header("7. Generera och skriv ut")
    included = [t for t in project.tables if t.include]
    if not included:
        st.info("Det finns inga tabeller att generera.")
        return
    a, b, c = st.columns([1, 1, 1.4])
    project.seed = int(a.number_input("Slumpfrö", value=int(project.seed), step=1, help="Samma frö och samma inställningar ger samma data varje gång – bra för reproducerbara tester."))
    project.locale = b.selectbox("Språk/land för namn och adresser", LOCALES, index=LOCALES.index(project.locale) if project.locale in LOCALES else 0)
    names = list(project.scenarios) or ["mellan"]
    default = next((i for i, n in enumerate(names) if project.scenarios.get(n) == 1), 0)
    scen = c.selectbox("Scenario (storlek)", names, index=default, format_func=lambda n: f"{n} (× {project.scenarios.get(n, 1):g})",
                       help="Multiplicerar radantalen. Kodtabeller och kalendrar påverkas inte.")
    scale = float(project.scenarios.get(scen, 1.0))

    x, y = st.columns(2)
    with x.expander("Scenarier"):
        text = st.text_area("Ett scenario per rad: namn = faktor", "\n".join(f"{k} = {v:g}" for k, v in project.scenarios.items()), height=110, key=f"scen_{ss.ver}")
        if st.button("Spara scenarier"):
            new = {}
            for line in text.splitlines():
                k, sep, v = line.partition("=")
                try:
                    if sep and k.strip() and float(v.replace(",", ".")) > 0:
                        new[k.strip()] = float(v.replace(",", "."))
                except ValueError:
                    pass
            if new:
                project.scenarios = new
                changed()
                st.rerun()
    with y.expander("Smutsig data" + (" – på" if project.dirty.get("tables") else "")):
        st.caption("Lägger in avsiktliga kvalitetsproblem i valda tabeller, som i riktiga källsystem. Nyckelkolumner rörs inte, "
                   "så datan går fortfarande att ladda. Föräldralösa nycklar skapas bara i egna relationer (som inte finns som FK i databasen).")
        d = project.dirty or {}
        keys = [t.key for t in included]
        dt = st.multiselect("Tabeller", keys, default=[k for k in d.get("tables") or [] if k in keys], key=f"dirty_t_{ss.ver}")
        dp = st.slider("Andel berörda rader per typ (%)", 1, 25, int(d.get("pct", 3)), key=f"dirty_p_{ss.ver}")
        dk = st.multiselect("Typer av problem", list(DIRTY_KINDS), default=[k for k in (d.get("kinds") or list(DIRTY_KINDS)) if k in DIRTY_KINDS],
                            format_func=lambda k: DIRTY_KINDS[k], key=f"dirty_k_{ss.ver}")
        new = {"tables": dt, "pct": dp, "kinds": dk} if dt else {}
        if new != (project.dirty or {}):
            project.dirty = new
            ss.result = None

    mode = st.radio("Körning", MODES, horizontal=True)
    append_cfg = None
    if mode == MODES[1]:
        st.caption("För att testa delta-laddningar: befintliga rader i databasen ligger kvar. Valda tabeller får nya rader vars löpnummer "
                   "fortsätter efter de befintliga, med datum från och med angivet datum. Övriga tabeller läses från databasen "
                   "(högst 50 000 rader per tabell) så att de nya raderna pekar på föräldrar som redan finns.")
        if not conn_label():
            st.info("Fyll i databasanslutningen under steg 1 först.")
        keys = [t.key for t in included]
        new_tables = st.multiselect("Tabeller som får nya rader", keys, default=[t.key for t in included if t.category in ("transaction", "bridge")])
        p1, p2, _ = st.columns([1, 1, 2])
        frac = float(p1.number_input("Andel av tabellens radantal (%)", 0.1, 100.0, 5.0))
        since = p2.date_input("Nya rader får datum från och med", date.today() - timedelta(days=1))
        append_cfg = (set(new_tables), since, frac / 100)

    total = sum(estimated_rows(project, t, scale) for t in included)
    label = f"Generera cirka {total:,} rader i {len(included)} tabeller".replace(",", " ") if append_cfg is None else "Generera nya rader"
    if st.button(label, type="primary"):
        bar = st.progress(0.0, "Genererar …")
        try:
            append = None
            if append_cfg is not None:
                append = dbio.prepare_append(get_engine(), project, append_cfg[0], append_cfg[1], append_cfg[2])
            ss.result = generate(project, scale=scale, append=append,
                                 progress=lambda key, done, total: bar.progress(done / max(total, 1), f"Genererar {key} …" if key else "Klart"))
            ss.result_append = append_cfg is not None
        except Exception as e:
            st.error(f"Genereringen misslyckades: {e}")
        bar.empty()

    res = ss.result
    if res is None:
        st.caption("Datan skapas i minnet först, så att du kan granska den innan något skrivs till databas eller fil.")
        return
    is_append = bool(ss.get("result_append"))

    n_rows = sum(len(res.data[k].rows) for k in res.order)
    st.success(f"{n_rows:,} rader genererade i {len(res.order)} tabeller.".replace(",", " ")
               + (f" {len(res.existing)} tabeller lästes från databasen och skrivs inte." if res.existing else ""))
    if res.warnings:
        with st.expander(f"⚠️ {len(res.warnings)} varningar", expanded=True):
            for w in res.warnings:
                st.write("• " + w)
    tab_data, tab_quality = st.tabs(["Granska data", "Kvalitetsrapport"])
    with tab_data:
        x, y = st.columns([1, 2.2], gap="large")
        with x:
            st.dataframe(pd.DataFrame([{"Tabell": k, "Rader": len(res.data[k].rows)} for k in res.order]), hide_index=True, width="stretch")
        with y:
            pickd = st.selectbox("Granska tabell", res.order)
            st.dataframe(to_df(res.data[pickd], 500), hide_index=True, width="stretch", height=320)
    with tab_quality:
        keys_df = pd.DataFrame(quality.key_report(res))
        rel_df = pd.DataFrame(quality.relation_report(res))
        dup = int(keys_df["Dubbletter"].sum()) if len(keys_df) else 0
        orphans = int(rel_df["Föräldralösa"].sum()) if len(rel_df) else 0
        m1, m2, m3 = st.columns(3)
        m1.metric("Dubbletter i nycklar", dup)
        m2.metric("Föräldralösa rader", orphans)
        m3.metric("Avsiktliga kvalitetsproblem", len(res.dirty_log))
        if res.dirty_log:
            with st.expander("Inlagda kvalitetsproblem (smutsig data)"):
                for line in res.dirty_log:
                    st.write("• " + line)
        if len(rel_df):
            st.write("**Relationer**")
            st.dataframe(rel_df, hide_index=True, width="stretch")
        qpick = st.selectbox("Kolumner i tabell", res.order, key="q_table")
        st.dataframe(pd.DataFrame(quality.column_report(res.data[qpick])), hide_index=True, width="stretch")

    st.subheader("Skriv ut")
    tab_db, tab_csv, tab_pq, tab_sql = st.tabs(["Databas", "CSV", "Parquet", "SQL-skript"])
    folder_default = f"output/{project.name.strip().replace(' ', '_') or 'projekt'}"
    with tab_db:
        target = conn_label()
        if not target:
            st.info("Ingen databas vald. Fyll i anslutningen under steg 1 (du behöver inte läsa in schemat därifrån).")
        else:
            st.write(f"Mål: **{target}**. Tabellerna laddas i beroendeordning i en enda transaktion – går något fel rullas allt tillbaka.")
            create = st.checkbox("Skapa tabeller som saknas i databasen", any(t.custom for t in included))
            empty = False if is_append else st.checkbox("Töm tabellerna först (DELETE)", False)
            if is_append:
                st.caption("Inkrementell körning: befintliga rader ligger kvar och de nya läggs till.")
            sure = True
            if empty:
                sure = st.checkbox(f"Jag förstår att alla befintliga rader i de {len(res.order)} tabellerna i {target} raderas", False)
            if st.button("Ladda till databasen", type="primary", disabled=not sure):
                bar = st.progress(0.0, "Laddar …")
                try:
                    written, warns = dbio.write_database(get_engine(), res, empty_first=empty, create_missing=create,
                                                         progress=lambda key, done, total: bar.progress(min(done / total, 1.0), f"Laddar {key} …"))
                    st.success(f"{sum(written.values()):,} rader laddade till {target}.".replace(",", " "))
                    for w in warns:
                        st.warning(w)
                except Exception as e:
                    st.error(f"Laddningen misslyckades och inget har sparats: {e}")
                    st.caption("Vanliga orsaker: tabellen innehåller redan rader med samma nycklar (töm först eller kör inkrementellt), "
                               "eller en NOT NULL-kolumn saknas i projektet.")
                bar.empty()
    with tab_csv:
        folder = st.text_input("Mapp", folder_default + "/csv", key="csv_folder")
        delim = st.selectbox("Avgränsare", [";", ",", "tab"], key="csv_delim")
        if st.button("Skriv CSV-filer"):
            paths = export.write_csv(res, folder, "\t" if delim == "tab" else delim)
            st.success(f"{len(paths)} filer skrivna till {Path(folder).resolve()}")
    with tab_pq:
        folder = st.text_input("Mapp", folder_default + "/parquet", key="pq_folder")
        if st.button("Skriv Parquet-filer"):
            try:
                paths = export.write_parquet(res, folder)
                st.success(f"{len(paths)} filer skrivna till {Path(folder).resolve()}")
            except Exception as e:
                st.error(f"Kunde inte skriva Parquet: {e}")
    with tab_sql:
        path = st.text_input("Fil", folder_default + "/dummydata.sql", key="sql_path")
        empty = st.checkbox("Inled skriptet med DELETE för alla tabeller", False, key="sql_empty", disabled=is_append)
        if st.button("Skriv SQL-skript"):
            out = export.write_sql(res, path, empty_first=empty and not is_append)
            st.success(f"Skriptet är skrivet till {out.resolve()}")


{PAGES[0]: page_source, PAGES[1]: page_diagram, PAGES[2]: page_tables, PAGES[3]: page_columns, PAGES[4]: page_lists,
 PAGES[5]: page_generators, PAGES[6]: page_generate}[page]()

# automatisk sparning: körs efter varje ändring (en körning som avbryts av st.rerun sparas av körningen som följer)
ss.project.connection = dict(ss.conn)  # utan lösenord – det ligger bara i sessionen
library.snapshot_into(ss.project)
try:
    ss.project_hash = store.save(ss.project_id, ss.project, ss.project_hash)
except KeyError:  # projektet har tagits bort i en annan flik: spara som nytt
    ss.project_id, ss.project_hash = store.create(ss.project, "Återskapat")
except Exception as e:
    st.sidebar.error(f"Kunde inte spara automatiskt: {e}")
