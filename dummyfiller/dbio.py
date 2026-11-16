"""Databasåtkomst: anslutning, inläsning av schema (endast metadata) och laddning av genererad data."""
from __future__ import annotations

from typing import Callable

import sqlalchemy as sa
from sqlalchemy.engine import URL, Engine

from .engine import Append, Result, TableData
from .model import Column, ForeignKey, Project, Table

AUTH_MODES = ["Windows-inloggning", "SQL Server-inloggning", "Microsoft Entra (interaktiv)"]
_SYSTEM_SCHEMAS = {"sys", "information_schema", "guest", "db_owner", "db_accessadmin", "db_securityadmin", "db_ddladmin",
                   "db_backupoperator", "db_datareader", "db_datawriter", "db_denydatareader", "db_denydatawriter"}


def list_drivers() -> list[str]:
    try:
        import pyodbc
        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:
        drivers = []
    def rank(d: str):
        digits = "".join(ch for ch in d if ch.isdigit())
        return ("ODBC Driver" not in d, -int(digits or 0))
    return sorted(drivers, key=rank)  # nyaste ODBC-drivrutinen först


def build_url(server: str, database: str, auth: str = AUTH_MODES[0], user: str = "", password: str = "",
              driver: str = "ODBC Driver 18 for SQL Server", encrypt: bool = True, trust_cert: bool = True, read_only: bool = False) -> URL:
    parts = [f"DRIVER={{{driver}}}", f"SERVER={server}", f"DATABASE={database}"]
    if auth == AUTH_MODES[0]:
        parts.append("Trusted_Connection=yes")
    elif auth == AUTH_MODES[1]:
        parts += [f"UID={user}", "PWD={" + password.replace("}", "}}") + "}"]
    else:
        parts.append("Authentication=ActiveDirectoryInteractive")
        if user:
            parts.append(f"UID={user}")
    parts.append(f"Encrypt={'yes' if encrypt else 'no'}")
    if trust_cert:
        parts.append("TrustServerCertificate=yes")
    if read_only:  # läsavsikt: kan styras till en läsbar replika, och markerar att inget ska skrivas
        parts.append("ApplicationIntent=ReadOnly")
    return URL.create("mssql+pyodbc", query={"odbc_connect": ";".join(parts)})


def make_engine(url) -> Engine:
    kwargs = {}
    if str(url).startswith("mssql+pyodbc") or getattr(url, "drivername", "") == "mssql+pyodbc":
        kwargs["fast_executemany"] = True
    return sa.create_engine(url, **kwargs)


def test_connection(engine: Engine) -> str:
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT 1"))
    return engine.dialect.name


def list_schemas(engine: Engine) -> list[str]:
    insp = sa.inspect(engine)
    return [s for s in insp.get_schema_names() if s.lower() not in _SYSTEM_SCHEMAS]


def reflect(engine: Engine, schemas: list[str] | None = None, progress: Callable[[str], None] | None = None) -> list[Table]:
    """Läser tabeller, kolumner, nycklar och relationer. Ingen tabelldata läses."""
    insp = sa.inspect(engine)
    mssql = engine.dialect.name == "mssql"
    has_schemas = engine.dialect.name != "sqlite"
    if has_schemas:
        wanted = schemas or [s for s in insp.get_schema_names() if s.lower() not in _SYSTEM_SCHEMAS]
    else:
        wanted = [None]
    default = insp.default_schema_name if has_schemas else ""
    tables: list[Table] = []
    for schema in wanted:
        for name in insp.get_table_names(schema=schema):
            if progress:
                progress(f"{schema}.{name}" if schema else name)
            t = Table(name=name, schema=schema or "")
            for c in insp.get_columns(name, schema=schema):
                try:
                    type_raw = str(c["type"])
                except Exception:
                    type_raw = type(c["type"]).__name__
                col = Column.from_type(c["name"], type_raw, mssql=mssql, nullable=bool(c.get("nullable", True)),
                                       identity=bool(c.get("identity")), computed=bool(c.get("computed")))
                col.default = str(c["default"]) if c.get("default") is not None else None
                t.columns.append(col)
            pk = insp.get_pk_constraint(name, schema=schema) or {}
            t.primary_key = list(pk.get("constrained_columns") or [])
            for fk in insp.get_foreign_keys(name, schema=schema):
                rschema = fk.get("referred_schema") or (schema if has_schemas else "") or default or ""
                ref_key = f"{rschema}.{fk['referred_table']}" if rschema else fk["referred_table"]
                t.foreign_keys.append(ForeignKey(columns=list(fk["constrained_columns"]), ref_table=ref_key,
                                                 ref_columns=list(fk["referred_columns"]), name=fk.get("name") or ""))
            uniques = [list(u["column_names"]) for u in insp.get_unique_constraints(name, schema=schema)]
            for ix in insp.get_indexes(name, schema=schema):
                cols = [c for c in ix.get("column_names") or [] if c]
                if ix.get("unique") and cols and cols not in uniques and cols != t.primary_key:
                    uniques.append(cols)
            t.uniques = uniques
            try:
                t.checks = [str(ck["sqltext"]) for ck in insp.get_check_constraints(name, schema=schema)]
            except Exception:  # alla dialekter stöder inte CHECK-inläsning
                t.checks = []
            tables.append(t)
    return tables


# ---------------------------------------------------------------- inkrementell körning

def prepare_append(engine: Engine, project: Project, new_tables: set[str], since=None, fraction: float = 1.0,
                   limit: int = 50000) -> Append:
    """Läser det som behövs för att lägga nya rader ovanpå befintlig (dummy-)data i databasen.

    För tabeller som får nya rader: radantal, högsta löpnummer och befintliga unika nycklar.
    För övriga tabeller: befintliga rader (högst `limit`), så att nya rader kan peka på dem.
    """
    ap = Append(new_tables=set(new_tables), since=since, fraction=fraction)
    md = sa.MetaData()
    with engine.connect() as conn:
        for t in project.tables:
            if not t.include:
                continue
            try:
                tbl = sa.Table(t.name, md, schema=t.schema or None, autoload_with=conn)
            except sa.exc.NoSuchTableError:
                continue
            cols = [c.name for c in t.columns if not c.computed and c.name in tbl.c]
            if t.key in ap.new_tables:
                ap.counts[t.key] = conn.execute(sa.select(sa.func.count()).select_from(tbl)).scalar() or 0
                ints = [c.name for c in t.columns if c.kind == "int" and c.name in tbl.c and c.generator == "sequence"]
                if ints:
                    row = conn.execute(sa.select(*[sa.func.max(tbl.c[n]) for n in ints])).one()
                    ap.maxima[t.key] = {n: v for n, v in zip(ints, row) if v is not None}
                sets = {}
                for u in [t.primary_key] + t.uniques:
                    if u and all(n in tbl.c for n in u):
                        found = conn.execute(sa.select(*[tbl.c[n] for n in u]).limit(limit * 4)).all()
                        sets[tuple(u)] = {tuple(r) for r in found}
                ap.existing_keys[t.key] = sets
            else:
                data = TableData(t, cols)
                data.rows = [list(r) for r in conn.execute(sa.select(*[tbl.c[n] for n in cols]).limit(limit)).all()]
                ap.existing[t.key] = data
    return ap


def list_tables(engine: Engine, schemas: list[str] | None = None, views: bool = True) -> list[dict]:
    """Tabeller (och vyer) med kolumner och datatyper – bara metadata, ingen data. Används för matchning mot produktion."""
    from .model import parse_type
    insp = sa.inspect(engine)
    mssql = engine.dialect.name == "mssql"
    if engine.dialect.name == "sqlite":
        wanted = [None]
    else:
        wanted = schemas or [s for s in insp.get_schema_names() if s.lower() not in _SYSTEM_SCHEMAS]
    out = []
    for schema in wanted:
        names = [(n, False) for n in insp.get_table_names(schema=schema)]
        if views:
            try:
                names += [(n, True) for n in insp.get_view_names(schema=schema)]
            except Exception:
                pass
        for name, is_view in names:
            cols = []
            for c in insp.get_columns(name, schema=schema):
                try:
                    type_raw = str(c["type"])
                except Exception:
                    type_raw = type(c["type"]).__name__
                cols.append({"name": c["name"], "type": type_raw, "kind": parse_type(type_raw, mssql)["kind"]})
            out.append({"schema": schema or "", "name": name, "view": is_view, "columns": cols})
    return out


# ---------------------------------------------------------------- skriva

def _sa_type(col: Column):
    k = col.kind
    raw = col.type_raw.lower()
    if k == "int":
        return sa.BigInteger() if "big" in raw else sa.SmallInteger() if "small" in raw or "tiny" in raw else sa.Integer()
    if k == "decimal":
        return sa.Numeric(col.precision or 18, col.scale or 0)
    if k == "float":
        return sa.Float()
    if k == "bool":
        return sa.Boolean()
    if k == "date":
        return sa.Date()
    if k == "datetime":
        return sa.DateTime()
    if k == "time":
        return sa.Time()
    if k == "uuid":
        return sa.Uuid(as_uuid=False)
    if k == "binary":
        return sa.LargeBinary(col.length)
    return sa.Unicode(col.length) if col.length else sa.UnicodeText()


def build_sa_table(table: Table, md: sa.MetaData, with_fks: set[str]) -> sa.Table:
    """Skapar en tabelldefinition från modellen (för tabeller som inte finns i databasen)."""
    cols = []
    for c in table.columns:
        if c.computed:
            continue
        args = [sa.Identity()] if c.identity else []
        cols.append(sa.Column(c.name, _sa_type(c), *args, nullable=c.nullable and c.name not in table.primary_key,
                              primary_key=c.name in table.primary_key, autoincrement=bool(c.identity)))
    constraints = []
    for fk in table.foreign_keys:
        if fk.ref_table in with_fks and fk.ref_table != table.key:
            constraints.append(sa.ForeignKeyConstraint(fk.columns, [f"{fk.ref_table}.{rc}" for rc in fk.ref_columns]))
    for u in table.uniques:
        constraints.append(sa.UniqueConstraint(*u))
    return sa.Table(table.name, md, *cols, *constraints, schema=table.schema or None)


def write_database(engine: Engine, result: Result, empty_first: bool = False, create_missing: bool = False,
                   batch_size: int = 1000, progress: Callable[[str, int, int], None] | None = None) -> tuple[dict[str, int], list[str]]:
    """Laddar tabellerna i beroendeordning i en enda transaktion. Returnerar (rader per tabell, varningar)."""
    md = sa.MetaData()
    warnings: list[str] = []
    written: dict[str, int] = {}
    with engine.begin() as conn:
        sa_tables: dict[str, sa.Table] = {}
        created: set[str] = set()
        for key in result.order:
            t = result.data[key].table
            try:
                sa_tables[key] = sa.Table(t.name, md, schema=t.schema or None, autoload_with=conn)
            except sa.exc.NoSuchTableError:
                if not create_missing:
                    raise RuntimeError(f"Tabellen {key} finns inte i databasen. Kryssa i 'Skapa tabeller som saknas' eller exkludera tabellen.")
                tbl = build_sa_table(t, md, set(sa_tables) | created)
                tbl.create(conn)
                sa_tables[key] = tbl
                created.add(key)
                warnings.append(f"{key}: tabellen fanns inte och har skapats")
        if empty_first:
            for key in reversed(result.order):
                if key not in created:
                    conn.execute(sa_tables[key].delete())
        total = sum(len(d.rows) for d in result.data.values()) or 1
        done = 0
        for key in result.order:
            data, tbl = result.data[key], sa_tables[key]
            db_cols = {c.name for c in tbl.columns}
            use = [(i, c) for i, c in enumerate(data.columns) if c in db_cols]
            missing = [c for c in data.columns if c not in db_cols]
            if missing:
                warnings.append(f"{key}: kolumnerna {', '.join(missing)} finns inte i databasen och hoppades över")
            stmt = tbl.insert()
            for start in range(0, len(data.rows), batch_size):
                chunk = data.rows[start:start + batch_size]
                conn.execute(stmt, [{c: row[i] for i, c in use} for row in chunk])
                done += len(chunk)
                if progress:
                    progress(key, done, total)
            written[key] = len(data.rows)
    return written, warnings
