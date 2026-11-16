"""Profil från produktion utan att någon rad lämnar den.

build_profile_sql() skapar ett T-SQL-skript som någon med produktionsåtkomst kör. Det returnerar bara aggregat:
radantal, andel NULL, min/max/medel för tal, min/max för datum och värdefördelning för kolumner med få unika värden.
Värden som förekommer färre än `min_count` gånger tas inte med, och identifierande kolumner hoppas över helt.
Resultatet sparas som CSV och läses in med apply_profile(), som ställer in vikter, intervall och radantal.
"""
from __future__ import annotations

import csv
import io

from .model import Project

# kolumner med dessa generatorer är identifierande eller fritext och profileras aldrig på värdenivå
_SENSITIVE = ("person.", "address.street", "address.full", "address.postcode", "phone", "company.", "text.", "internet.",
              "finance.", "faker", "uuid", "care.hsa", "pattern", "sequence", "expression", "parent.lookup")
METRICS = {"rows", "null", "min", "max", "avg", "sd", "value"}


def _q(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def _lit(s: str) -> str:
    return "N'" + s.replace("'", "''") + "'"


def build_profile_sql(project: Project, max_distinct: int = 50, min_count: int = 5) -> str:
    out = [
        "-- Profil för dummyfiller. Returnerar endast aggregat, inga enskilda rader.",
        f"-- Värden som förekommer färre än {min_count} gånger utelämnas. Identifierande kolumner och fritext ingår inte.",
        "-- Kör skriptet, spara resultatet som CSV (med rubriker) och läs in filen under steg 5 → Profil från produktion.",
        "SET NOCOUNT ON;",
        "CREATE TABLE #profil (tabell nvarchar(300), kolumn nvarchar(200), matt varchar(10), varde nvarchar(400), antal bigint);",
    ]
    for t in project.tables:
        if not t.include or t.custom:
            continue
        tn = (_q(t.schema) + "." if t.schema else "") + _q(t.name)
        key = _lit(t.key)
        keys = set(t.primary_key) | {c for u in t.uniques for c in u} | {c for fk in t.foreign_keys for c in fk.columns}
        out.append(f"\n-- {t.key}")
        out.append(f"INSERT INTO #profil SELECT {key}, N'', 'rows', NULL, COUNT_BIG(*) FROM {tn};")
        for c in t.columns:
            if c.computed or c.custom or c.kind in ("binary", "other", "uuid"):
                continue
            cn, name = _q(c.name), _lit(c.name)
            if c.nullable:
                out.append(f"INSERT INTO #profil SELECT {key}, {name}, 'null', NULL, COUNT_BIG(*) FROM {tn} WHERE {cn} IS NULL;")
            if c.name in keys or c.generator.startswith(_SENSITIVE):
                continue
            if c.kind in ("int", "decimal", "float"):
                out.append(
                    f"INSERT INTO #profil SELECT {key}, {name}, m.matt, CONVERT(nvarchar(60), CAST(m.v AS decimal(38, 6))), NULL "
                    f"FROM (SELECT MIN(CAST({cn} AS float)) mn, MAX(CAST({cn} AS float)) mx, AVG(CAST({cn} AS float)) av, "
                    f"STDEV(CAST({cn} AS float)) sd FROM {tn}) x "
                    "CROSS APPLY (VALUES ('min', x.mn), ('max', x.mx), ('avg', x.av), ('sd', x.sd)) m(matt, v) WHERE m.v IS NOT NULL;")
            elif c.kind in ("date", "datetime"):
                out.append(
                    f"INSERT INTO #profil SELECT {key}, {name}, m.matt, CONVERT(nvarchar(10), m.v, 23), NULL "
                    f"FROM (SELECT MIN(CAST({cn} AS date)) mn, MAX(CAST({cn} AS date)) mx FROM {tn}) x "
                    "CROSS APPLY (VALUES ('min', x.mn), ('max', x.mx)) m(matt, v) WHERE m.v IS NOT NULL;")
            if c.kind == "bool" or c.kind == "int" or (c.kind == "string" and (c.length or 9999) <= 100):
                out.append(
                    f"IF (SELECT COUNT(DISTINCT {cn}) FROM {tn}) <= {int(max_distinct)}\n"
                    f"    INSERT INTO #profil SELECT {key}, {name}, 'value', CONVERT(nvarchar(400), {cn}), COUNT_BIG(*) "
                    f"FROM {tn} WHERE {cn} IS NOT NULL GROUP BY {cn} HAVING COUNT_BIG(*) >= {int(min_count)};")
    out.append("\nSELECT tabell, kolumn, matt, varde, antal FROM #profil ORDER BY tabell, kolumn, matt, antal DESC;")
    out.append("DROP TABLE #profil;")
    return "\n".join(out) + "\n"


def parse_profile(text: str) -> list[tuple[str, str, str, str | None, int | None]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    delim = max((";", "\t", ","), key=lambda d: lines[0].count(d))
    rows = []
    for r in csv.reader(io.StringIO("\n".join(lines)), delimiter=delim):
        if len(r) < 5 or r[2].strip().lower() not in METRICS:
            continue
        value = r[3].strip()
        count = r[4].strip()
        rows.append((r[0].strip(), r[1].strip(), r[2].strip().lower(), None if value.upper() in ("", "NULL") else value,
                     int(float(count)) if count and count.upper() != "NULL" else None))
    return rows


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def apply_profile(project: Project, rows: list[tuple], use_rows: bool = True, rows_factor: float = 1.0) -> dict[str, int]:
    """Tillämpar profilen på projektet. Returnerar antal ändringar per typ."""
    done = {"radantal": 0, "andel NULL": 0, "värdefördelningar": 0, "talintervall": 0, "datumintervall": 0}
    by_col: dict[tuple[str, str], dict] = {}
    table_rows: dict[str, int] = {}
    for tkey, cname, metric, value, count in rows:
        if metric == "rows":
            table_rows[tkey.lower()] = count or 0
            continue
        d = by_col.setdefault((tkey.lower(), cname.lower()), {"values": []})
        if metric == "value":
            d["values"].append((value, count or 0))
        elif metric == "null":
            d["null"] = count or 0
        else:
            d[metric] = value
    for t in project.tables:
        total = table_rows.get(t.key.lower())
        if total is not None and use_rows:
            t.rows = max(1, round(total * rows_factor)) if total else 0
            done["radantal"] += 1
        keys = set(t.primary_key) | {c for fk in t.foreign_keys for c in fk.columns}
        for c in t.columns:
            d = by_col.get((t.key.lower(), c.name.lower()))
            if not d:
                continue
            if "null" in d and total and c.nullable:
                c.null_pct = round(min(100.0, d["null"] * 100 / total), 1)
                done["andel NULL"] += 1
            if c.name in keys or c.computed:
                continue
            vals = [(v, n) for v, n in d["values"] if v is not None and n > 0]
            if vals and c.kind == "bool":
                true = sum(n for v, n in vals if v.strip().lower() in ("1", "true"))
                c.generator, c.params = "bool", {"true_pct": round(true * 100 / sum(n for _, n in vals), 1)}
                c.manual, c.confidence = True, ""
                done["värdefördelningar"] += 1
            elif vals:
                c.generator = "choice"
                c.params = {"values": "\n".join(f"{v} | {n}" for v, n in sorted(vals, key=lambda x: -x[1])), "mode": "Slumpad (enligt vikt)"}
                c.manual, c.confidence = True, ""
                done["värdefördelningar"] += 1
            elif c.kind in ("int", "decimal", "float") and (lo := _num(d.get("min"))) is not None and (hi := _num(d.get("max"))) is not None:
                if not (c.generator.startswith("number.") or c.confidence == "låg"):
                    continue
                avg, sd = _num(d.get("avg")), _num(d.get("sd"))
                dist = "Jämn"
                if avg is not None and hi > lo:
                    pos = (avg - lo) / (hi - lo)
                    dist = "Skev (många låga)" if pos < 0.33 else "Normal (flest i mitten)" if sd and pos < 0.67 else "Jämn"
                if c.kind == "int":
                    c.generator, c.params = "number.int", {"min": int(lo), "max": int(hi), "distribution": dist}
                else:
                    c.generator, c.params = "number.decimal", {"min": lo, "max": hi, "decimals": c.scale if c.scale is not None else 2, "distribution": dist}
                c.manual, c.confidence = True, ""
                done["talintervall"] += 1
            elif c.kind in ("date", "datetime") and d.get("min") and d.get("max") and c.generator == "date.between":
                c.params = {**c.params, "start": d["min"][:10], "end": d["max"][:10]}
                c.manual, c.confidence = True, ""
                done["datumintervall"] += 1
    return done
