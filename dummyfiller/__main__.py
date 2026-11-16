"""Kommandorad för dummyfiller.

    python -m dummyfiller                      startar webbgränssnittet
    python -m dummyfiller generate p.yaml ...  genererar data utan gränssnitt (för skript och pipelines)
    python -m dummyfiller profile-sql p.yaml   skapar skriptet för profil från produktion
    python -m dummyfiller apply-profile p.yaml resultat.csv
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path


def run_ui(port: str = "8501") -> int:
    app = Path(__file__).with_name("app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", str(app),
           "--server.address=localhost",          # nås bara från den egna datorn
           "--server.port", str(port),
           "--server.headless=true",              # ingen e-postfråga vid första start
           "--browser.gatherUsageStats=false"]    # ingen användningsstatistik skickas
    threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def _engine(project, url: str | None):
    from . import dbio
    if url:
        return dbio.make_engine(url)
    c = project.connection or {}
    if c.get("mode") == "Egen SQLAlchemy-URL" and c.get("url"):
        return dbio.make_engine(c["url"])
    if not c.get("server") or not c.get("database"):
        raise SystemExit("Projektet saknar databasanslutning. Ange --url eller spara anslutningen i projektet via gränssnittet.")
    return dbio.make_engine(dbio.build_url(c["server"], c["database"], c.get("auth") or dbio.AUTH_MODES[0], c.get("user", ""),
                                           os.environ.get("DUMMYFILLER_PASSWORD", ""), c.get("driver") or (dbio.list_drivers() or ["ODBC Driver 18 for SQL Server"])[0],
                                           c.get("encrypt", True), c.get("trust", True)))


def cmd_generate(a) -> int:
    from . import dbio, export
    from .engine import generate
    from .model import Project

    project = Project.load(a.project)
    if a.bibliotek:
        from . import library
        library.use_file(a.bibliotek)
    if a.seed is not None:
        project.seed = a.seed
    scale = 1.0
    if a.scenario:
        if a.scenario not in project.scenarios:
            raise SystemExit(f"Okänt scenario '{a.scenario}'. Finns: {', '.join(project.scenarios)}")
        scale = float(project.scenarios[a.scenario])
    if a.scale is not None:
        scale = a.scale
    append = None
    engine = None
    if a.append:
        if a.target != "db":
            raise SystemExit("--append kräver --target db.")
        engine = _engine(project, a.url)
        new = set(a.tables.split(",")) if a.tables else {t.key for t in project.tables if t.include and t.category in ("transaction", "bridge")}
        since = date.fromisoformat(a.since) if a.since else date.today()
        append = dbio.prepare_append(engine, project, new, since, a.fraction / 100)
    result = generate(project, scale=scale, append=append)
    for w in result.warnings:
        print("VARNING:", w, file=sys.stderr)
    name = project.name.strip().replace(" ", "_") or "projekt"
    if a.target == "db":
        engine = engine or _engine(project, a.url)
        written, warns = dbio.write_database(engine, result, empty_first=a.empty_first and not a.append, create_missing=a.create_missing)
        for w in warns:
            print("VARNING:", w, file=sys.stderr)
        where = "databasen"
    elif a.target == "csv":
        where = a.out or f"output/{name}/csv"
        export.write_csv(result, where, a.delimiter)
    elif a.target == "parquet":
        where = a.out or f"output/{name}/parquet"
        export.write_parquet(result, where)
    else:
        where = str(export.write_sql(result, a.out or f"output/{name}/dummydata.sql", empty_first=a.empty_first))
    for key in result.order:
        print(f"{len(result.data[key].rows):>9}  {key}")
    print(f"{sum(len(result.data[k].rows) for k in result.order):>9}  rader skrivna till {where}")
    return 0


def cmd_profile_sql(a) -> int:
    from .model import Project
    from .prodprofile import build_profile_sql
    sql = build_profile_sql(Project.load(a.project), a.max_distinct, a.min_count)
    Path(a.out).write_text(sql, encoding="utf-8-sig")
    print(f"Skriptet är skrivet till {a.out}")
    return 0


def cmd_apply_profile(a) -> int:
    from .model import Project
    from .prodprofile import apply_profile, parse_profile
    from .valuelists import decode
    project = Project.load(a.project)
    done = apply_profile(project, parse_profile(decode(Path(a.csv).read_bytes())), not a.keep_rows, a.factor)
    project.save(a.project)
    print("Profilen är tillämpad: " + ", ".join(f"{n} {k}" for k, n in done.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].isdigit():  # bakåtkompatibelt: python -m dummyfiller [port]
        return run_ui(argv[0] if argv else "8501")
    ap = argparse.ArgumentParser(prog="dummyfiller", description="Verklighetstrogen dummy-data utifrån databasscheman.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    ui = sp.add_parser("ui", help="starta webbgränssnittet")
    ui.add_argument("--port", default="8501")

    g = sp.add_parser("generate", help="generera data från en sparad projektfil")
    g.add_argument("project", help="projektfil (YAML) sparad från gränssnittet")
    g.add_argument("--target", choices=["db", "csv", "parquet", "sql"], default="csv")
    g.add_argument("--out", help="mapp (csv/parquet) eller fil (sql)")
    g.add_argument("--scenario", help="namn på ett scenario i projektet, t.ex. liten")
    g.add_argument("--scale", type=float, help="skalfaktor för radantalen (går före --scenario)")
    g.add_argument("--seed", type=int, help="slumpfrö (annars projektets)")
    g.add_argument("--delimiter", default=";")
    g.add_argument("--url", help="SQLAlchemy-URL (annars projektets anslutning; lösenord läses från DUMMYFILLER_PASSWORD)")
    g.add_argument("--empty-first", action="store_true", help="töm tabellerna (DELETE) innan laddning")
    g.add_argument("--create-missing", action="store_true", help="skapa tabeller som saknas i databasen")
    g.add_argument("--append", action="store_true", help="inkrementell körning: lägg nya rader ovanpå befintliga")
    g.add_argument("--tables", help="vid --append: kommaseparerade tabeller som får nya rader (annars transaktionstabeller)")
    g.add_argument("--since", help="vid --append: nya rader får datum från och med ÅÅÅÅ-MM-DD (annars i dag)")
    g.add_argument("--fraction", type=float, default=5.0, help="vid --append: andel av tabellens radantal i procent")
    g.add_argument("--bibliotek", help="generatorbibliotek (YAML) att använda utöver det lokala, t.ex. teamets gemensamma fil")

    ib = sp.add_parser("import-bibliotek", help="läs in ett generatorbibliotek (YAML) i det lokala biblioteket")
    ib.add_argument("fil")
    eb = sp.add_parser("export-bibliotek", help="skriv det lokala generatorbiblioteket till en YAML-fil")
    eb.add_argument("fil")

    ps = sp.add_parser("profile-sql", help="skapa SQL-skriptet för profil från produktion (endast aggregat)")
    ps.add_argument("project")
    ps.add_argument("--out", default="profil.sql")
    ps.add_argument("--max-distinct", type=int, default=50)
    ps.add_argument("--min-count", type=int, default=5)

    pa = sp.add_parser("apply-profile", help="läs in profilresultatet (CSV) och uppdatera projektfilen")
    pa.add_argument("project")
    pa.add_argument("csv")
    pa.add_argument("--factor", type=float, default=0.01, help="radantal = produktionens × faktor")
    pa.add_argument("--keep-rows", action="store_true", help="ändra inte radantalen")

    a = ap.parse_args(argv)
    if a.cmd == "ui":
        return run_ui(a.port)
    if a.cmd in ("import-bibliotek", "export-bibliotek"):
        from . import library
        if a.cmd == "export-bibliotek":
            Path(a.fil).write_text(library.export_yaml(), encoding="utf-8")
            print(f"Biblioteket är skrivet till {a.fil}")
        else:
            n = library.import_yaml(Path(a.fil).read_text(encoding="utf-8"))
            print("Inläst: " + ", ".join(f"{v} {k}" for k, v in n.items()))
        return 0
    return {"generate": cmd_generate, "profile-sql": cmd_profile_sql, "apply-profile": cmd_apply_profile}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
