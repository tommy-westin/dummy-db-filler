"""Datamodell för ett projekt: tabeller, kolumner, relationer och inställningar."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

CATEGORIES = {
    "person": "Person (patient, anställd, invånare …)",
    "company": "Leverantör / organisation",
    "transaction": "Händelse / transaktion (vårdkontakt, faktura, budgetpost, frånvaro …)",
    "calendar": "Kalender / datumdimension",
    "location": "Enhet / plats (vårdenhet, klinik, adress …)",
    "reference": "Referens / kodtabell (konto, ansvar, diagnos, befattning …)",
    "bridge": "Kopplingstabell (många-till-många)",
    "other": "Övrigt",
}

DISTRIBUTIONS = {
    "random": "Slumpad (jämn)",
    "skewed": "Skev (några föräldrar får många rader)",
    "even": "Jämnt fördelad (i tur och ordning)",
    "unique": "En-till-en (varje förälder högst en gång)",
    "need": "Efter vårdbehov (äldre och kroniker oftare)",
}

_INT_RANGES = {
    "tinyint": (0, 255),
    "smallint": (-32768, 32767),
    "int": (-(2**31), 2**31 - 1),
    "integer": (-(2**31), 2**31 - 1),
    "mediumint": (-(2**23), 2**23 - 1),
    "bigint": (-(2**63), 2**63 - 1),
}


def parse_type(type_raw: str, mssql: bool = True) -> dict:
    """Tolkar en SQL-typ ('nvarchar(50)', 'DECIMAL(18, 2)' …) till kind/längd/precision/skala."""
    s = re.sub(r"\s+collate\s+\S+", "", type_raw.strip(), flags=re.I)
    m = re.match(r"\s*\[?([A-Za-z_][\w ]*?)\]?\s*(?:\(([^)]*)\))?\s*$", s)
    base = (m.group(1) if m else s).strip().lower()
    args = [a.strip().lower() for a in (m.group(2).split(",") if m and m.group(2) else [])]
    nums = [int(a) for a in args if a.isdigit()]
    out = {"kind": "other", "length": None, "precision": None, "scale": None, "computed": False}
    if base in _INT_RANGES or base in ("serial", "bigserial"):
        out["kind"] = "int"
    elif base in ("decimal", "numeric", "dec", "number"):
        out.update(kind="decimal", precision=nums[0] if nums else 18, scale=nums[1] if len(nums) > 1 else 0)
    elif base == "money":
        out.update(kind="decimal", precision=19, scale=4)
    elif base == "smallmoney":
        out.update(kind="decimal", precision=10, scale=4)
    elif base in ("float", "real", "double", "double precision"):
        out["kind"] = "float"
    elif base in ("bit", "boolean", "bool"):
        out["kind"] = "bool"
    elif base in ("char", "nchar", "varchar", "nvarchar", "character", "character varying", "string", "sysname"):
        out.update(kind="string", length=nums[0] if nums else (None if args else (1 if "var" not in base and base != "string" else None)))
        if base == "sysname":
            out["length"] = 128
    elif base in ("text", "ntext", "clob", "nclob", "longtext", "mediumtext"):
        out["kind"] = "string"
    elif base == "date":
        out["kind"] = "date"
    elif base in ("datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        out["kind"] = "datetime"
    elif base in ("timestamp", "rowversion"):
        if mssql or base == "rowversion":
            out.update(kind="binary", computed=True)  # rowversion sätts av SQL Server
        else:
            out["kind"] = "datetime"
    elif base == "time":
        out["kind"] = "time"
    elif base in ("uniqueidentifier", "uuid", "guid"):
        out["kind"] = "uuid"
    elif base in ("binary", "varbinary", "image", "blob"):
        out.update(kind="binary", length=nums[0] if nums else None)
    return out


def int_range(type_raw: str) -> tuple[int, int]:
    base = re.sub(r"[\[\]]", "", type_raw.strip().lower()).split("(")[0].strip()
    return _INT_RANGES.get(base, _INT_RANGES["bigint" if "big" in base else "int"])


@dataclass
class Column:
    name: str
    type_raw: str = "nvarchar(100)"
    kind: str = "string"
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool = True
    identity: bool = False
    computed: bool = False
    generator: str = ""
    params: dict = field(default_factory=dict)
    null_pct: float = 0.0
    manual: bool = False  # användaren har själv valt generator/parametrar
    confidence: str = ""  # "hög" / "låg" – hur säker den automatiska gissningen är
    custom: bool = False  # tillagd av användaren (finns inte i inläst schema)
    default: str | None = None  # standardvärde enligt schemat (text)

    @classmethod
    def from_type(cls, name: str, type_raw: str, mssql: bool = True, **kw) -> "Column":
        info = parse_type(type_raw, mssql)
        computed = kw.pop("computed", False) or info.pop("computed")
        info.pop("computed", None)
        return cls(name=name, type_raw=type_raw, computed=computed, **info, **kw)


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str  # nyckel "schema.tabell"
    ref_columns: list[str]
    name: str = ""
    distribution: str = "random"
    null_pct: float = 0.0
    source: str = "schema"  # schema | manual
    per_parent_min: int = 0  # barn per förälder; max > 0 gör att radantalet följer av föräldratabellen
    per_parent_max: int = 0
    guided: bool = False  # föräldern väljs utifrån värdet som kolumnens egen generator ger (t.ex. diagnoskod som passar patienten)


@dataclass
class Table:
    name: str
    schema: str = "dbo"
    columns: list[Column] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    uniques: list[list[str]] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    category: str = "other"
    category_manual: bool = False
    rows: int = 100
    include: bool = True
    custom: bool = False
    checks: list[str] = field(default_factory=list)  # CHECK-villkor enligt schemat
    history: dict = field(default_factory=dict)  # SCD2-inställningar, se engine
    pos: list = field(default_factory=list)  # [x, y] i diagrammet

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    def fk_for(self, column: str) -> ForeignKey | None:
        return next((fk for fk in self.foreign_keys if column in fk.columns), None)


@dataclass
class Project:
    name: str = "Nytt projekt"
    locale: str = "sv_SE"
    seed: int = 42
    tables: list[Table] = field(default_factory=list)
    value_lists: dict[str, list[str]] = field(default_factory=dict)
    connection: dict = field(default_factory=dict)  # utan lösenord
    scenarios: dict[str, float] = field(default_factory=lambda: {"liten": 0.1, "mellan": 1.0, "stor": 10.0})
    dirty: dict = field(default_factory=dict)  # {"pct": 3, "kinds": [...], "tables": [...]}
    codebooks: dict[str, list] = field(default_factory=dict)  # inlästa kodverk: diagnosis / procedure / drug -> [[kod, text], ...]
    test_pnr_list: str = ""  # värdelista med officiella testpersonnummer
    custom_generators: dict = field(default_factory=dict)  # kopia av egna generatorer som projektet använder
    prod_mapping: dict = field(default_factory=dict)  # koppling av tabeller och kolumner mot produktionen (se matching.py)

    def table(self, key: str) -> Table | None:
        low = key.lower()
        return next((t for t in self.tables if t.key.lower() == low), None)

    def remove_table(self, key: str) -> None:
        self.tables = [t for t in self.tables if t.key != key]
        for t in self.tables:
            t.foreign_keys = [fk for fk in t.foreign_keys if fk.ref_table != key]

    # ---- YAML ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        tables = []
        for td in d.get("tables", []):
            td = dict(td)
            cols = [Column(**c) for c in td.pop("columns", [])]
            fks = [ForeignKey(**f) for f in td.pop("foreign_keys", [])]
            tables.append(Table(columns=cols, foreign_keys=fks, **td))
        rest = {k: v for k, v in d.items() if k != "tables"}
        return cls(tables=tables, **rest)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)  # C-varianten är mycket snabbare för stora kodverk
        path.write_text(yaml.dump(self.to_dict(), Dumper=dumper, allow_unicode=True, sort_keys=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        return cls.from_dict(yaml.load(Path(path).read_text(encoding="utf-8"), Loader=loader) or {})


def merge_tables(project: Project, new_tables: list[Table]) -> tuple[int, int]:
    """Lägger in nyinlästa tabeller i projektet och behåller användarens inställningar.

    Returnerar (antal nya, antal uppdaterade)."""
    added = updated = 0
    for new in new_tables:
        old = project.table(new.key)
        if old is None:
            project.tables.append(new)
            added += 1
            continue
        updated += 1
        new.rows, new.include = old.rows, old.include
        if old.history:
            new.history = old.history
        new.pos = old.pos
        if old.category_manual:
            new.category, new.category_manual = old.category, True
        for col in new.columns:
            oc = old.column(col.name)
            if oc and oc.manual:
                col.generator, col.params, col.null_pct, col.manual = oc.generator, oc.params, oc.null_pct, True
        names = {c.name for c in new.columns}
        new.columns += [c for c in old.columns if c.custom and c.name not in names]
        names = {c.name for c in new.columns}
        for fk in new.foreign_keys:
            ofk = next((f for f in old.foreign_keys if f.columns == fk.columns and f.ref_table == fk.ref_table), None)
            if ofk:
                fk.distribution, fk.null_pct = ofk.distribution, ofk.null_pct
                fk.per_parent_min, fk.per_parent_max, fk.guided = ofk.per_parent_min, ofk.per_parent_max, ofk.guided
        have = {(tuple(f.columns), f.ref_table) for f in new.foreign_keys}
        new.foreign_keys += [
            f for f in old.foreign_keys
            if f.source == "manual" and (tuple(f.columns), f.ref_table) not in have and set(f.columns) <= names
        ]
        project.tables[project.tables.index(old)] = new
    return added, updated
