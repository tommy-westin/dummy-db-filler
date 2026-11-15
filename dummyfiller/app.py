"""Webbgränssnittet (Streamlit). Startas med:  python -m dummyfiller"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # så att paketet hittas även utan installation
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from datetime import date, timedelta  # noqa: E402

from dummyfiller import care, dbio, export, prodprofile, quality, rules, valuelists  # noqa: E402
from dummyfiller.ddl import parse_ddl  # noqa: E402
from dummyfiller.dirty import KINDS as DIRTY_KINDS  # noqa: E402
from dummyfiller.engine import estimated_rows, generate, load_order  # noqa: E402
from dummyfiller.generators import LABEL_TO_KEY, LIST_MODES, REGISTRY, defaults, label_of  # noqa: E402
from dummyfiller.inference import (default_fk_settings, default_rows, infer_column, infer_table, norm,  # noqa: E402
                                   suggest_relations)
from dummyfiller.model import CATEGORIES, DISTRIBUTIONS, Column, ForeignKey, Project, Table, merge_tables  # noqa: E402

st.set_page_config(page_title="Dummyfiller", page_icon="🧪", layout="wide")
ss = st.session_state
PAGES = ["1. Källa", "2. Tabeller och relationer", "3. Kolumner", "4. Värdelistor", "5. Generera"]
CAT_LABELS = list(CATEGORIES.values())
CAT_BY_LABEL = {v: k for k, v in CATEGORIES.items()}
DIST_LABELS = list(DISTRIBUTIONS.values())
DIST_BY_LABEL = {v: k for k, v in DISTRIBUTIONS.items()}
GEN_LABELS = [label_of(k) for k in REGISTRY]
COMPUTED_LABEL = "(sätts av databasen)"

ss.setdefault("project", Project())
ss.setdefault("ver", 0)
ss.setdefault("result", None)
ss.setdefault("flash", [])
ss.setdefault("conn", {"mode": "SQL Server", "server": "localhost", "database": "", "auth": dbio.AUTH_MODES[0], "user": "",
                       "driver": "", "encrypt": True, "trust": True, "url": "", "schemas": ""})
ss.setdefault("pw", "")
project: Project = ss.project


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
    if key == "parent.lookup" and table.foreign_keys:
        fk = table.foreign_keys[0]
        d["via"] = fk.columns[0]
        ref = project.table(fk.ref_table)
        if ref:
            d["column"] = next((c.name for c in ref.columns if c.name not in fk.ref_columns), ref.columns[0].name)
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

with st.sidebar:
    st.title("🧪 Dummyfiller")
    st.caption("Verklighetstrogen dummy-data utifrån dina scheman. Allt körs lokalt – ingen data hämtas från internet.")
    page = st.radio("Steg", PAGES, key="page")
    st.divider()
    project.name = st.text_input("Projektnamn", project.name)
    default_path = f"projekt/{project.name.strip().replace(' ', '_') or 'projekt'}.yaml"
    path = st.text_input("Projektfil", ss.get("project_path") or default_path, help="Projektet (schema, kategorier, generatorer, värdelistor) sparas som YAML och kan versionshanteras. Lösenord sparas aldrig.")
    c1, c2 = st.columns(2)
    if c1.button("Spara", width="stretch"):
        try:
            project.connection = dict(ss.conn)
            project.save(path)
            ss.project_path = path
            st.success(f"Sparat till {path}")
        except Exception as e:
            st.error(f"Kunde inte spara: {e}")
    if c2.button("Öppna", width="stretch"):
        try:
            ss.project = Project.load(path)
            ss.project_path = path
            if ss.project.connection:
                ss.conn.update(ss.project.connection)
            changed()
            st.rerun()
        except Exception as e:
            st.error(f"Kunde inte öppna: {e}")
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
                flash("success", f"Schemat är inläst: {added} nya tabeller, {updated} uppdaterade. Gå vidare till steg 2.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte läsa schemat: {e}")

    with tab_ddl:
        st.write("Ladda upp eller klistra in `CREATE TABLE`-skript (T-SQL, t.ex. skriptade från SSMS). `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` tolkas också.")
        files = st.file_uploader("SQL-filer", type=["sql", "txt", "ddl"], accept_multiple_files=True)
        pasted = st.text_area("… eller klistra in DDL", height=180)
        schema = st.text_input("Standardschema (för tabeller utan schema)", "dbo")
        b1, b2, _ = st.columns([1, 1.4, 3])
        sql = None
        if b1.button("Läs in DDL", type="primary"):
            sql = "\nGO\n".join([valuelists.decode(f.getvalue()) for f in files or []] + [pasted])
        example = ROOT / "exempel" / "vard.sql"
        if example.exists() and b2.button("Läs in exempelschema (vård)"):
            sql = example.read_text(encoding="utf-8")
        if sql is not None:
            tables, warns = parse_ddl(sql, schema or "dbo")
            if not tables:
                st.error("Hittade inga CREATE TABLE-satser att tolka.")
            else:
                added, updated = add_tables(tables)
                for w in warns:
                    flash("warning", w)
                flash("success", f"DDL inläst: {added} nya tabeller, {updated} uppdaterade. Gå vidare till steg 2.")
                st.rerun()

    with tab_manual:
        st.write("Du behöver inget schema för att komma igång. Under **2. Tabeller och relationer** kan du skapa egna tabeller "
                 "och relationer, och under **3. Kolumner** lägger du till kolumner – både i egna tabeller och som komplettering "
                 "till inlästa. Egna tabeller kan skapas i databasen vid laddning eller exporteras till fil.")


# ---------------------------------------------------------------- 2. Tabeller och relationer

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
    st.header("2. Tabeller och relationer")
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
            "Osäkra kolumner": st.column_config.NumberColumn(help="Kolumner där den automatiska tolkningen är en gissning – titta på dem under steg 3."),
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
                    flash("success", f"Tabellen {t.key} är skapad. Lägg till kolumner under steg 3.")
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
            "Barn per förälder, högst": st.column_config.NumberColumn(min_value=0, step=1, help="Större än 0: varje förälder får så här många barnrader, och tabellens radantal följer av föräldern (t.ex. 1–5 orderrader per order). 0 = använd tabellens radantal och fördelningen."),
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


# ---------------------------------------------------------------- 3. Kolumner

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
                st.caption("Inga värdelistor inlästa ännu – gör det under steg 4.")
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
    st.header("3. Kolumner – vad ska varje kolumn innehålla?")
    if not project.tables:
        st.info("Inga tabeller ännu. Börja med steg 1 eller skapa en tabell under steg 2.")
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
                        "Fördelning och andel NULL ställer du in under steg 2 → Relationer.")
            else:
                labels = GEN_LABELS
                cur_label = label_of(col.generator) if col.generator in REGISTRY else labels[0]
                picked = st.selectbox("Generator", labels, index=labels.index(cur_label), key=f"gen_{t.key}_{col.name}_{ss.ver}")
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
                t.columns = [c for c in t.columns if c.name != victim]
                t.primary_key = [c for c in t.primary_key if c != victim]
                t.uniques = [u for u in t.uniques if victim not in u]
                t.foreign_keys = [fk for fk in t.foreign_keys if victim not in fk.columns]
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


# ---------------------------------------------------------------- 4. Värdelistor

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
             "inbyggda tolkningsreglerna när ett schema läses in. Nya regler skapar du under steg 3 → 'Spara kolumnens inställning som regel'.")
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
    st.header("4. Värdelistor – styr datan med egna exempel")
    t1, t2, t3, t4 = st.tabs(["Värdelistor", "Kodverk (vård)", "Profil från produktion", "Egna regler"])
    with t1:
        tab_value_lists()
    with t2:
        tab_codebooks()
    with t3:
        tab_profile()
    with t4:
        tab_rules()


# ---------------------------------------------------------------- 5. Generera

LOCALES = ["sv_SE", "en_US", "en_GB", "nb_NO", "da_DK", "fi_FI", "de_DE"]
MODES = ["Ny datamängd", "Lägg till ny data ovanpå befintlig (inkrementellt)"]


def page_generate():
    st.header("5. Generera och skriv ut")
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


{PAGES[0]: page_source, PAGES[1]: page_tables, PAGES[2]: page_columns, PAGES[3]: page_lists, PAGES[4]: page_generate}[page]()
