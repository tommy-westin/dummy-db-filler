"""Kvalitetsrapport över genererad data: fyllnadsgrad, unika värden, spridning och relationsintegritet."""
from __future__ import annotations

from collections import Counter

from .engine import Result, TableData


def _fmt(v) -> str:
    s = str(v)
    return s if len(s) <= 30 else s[:29] + "…"


def column_report(data: TableData) -> list[dict]:
    out = []
    n = len(data.rows)
    for name in data.columns:
        col = data.table.column(name)
        vals = data.column_values(name)
        present = [v for v in vals if v is not None]
        try:
            counts = Counter(present)
        except TypeError:
            counts = Counter(str(v) for v in present)
        lo = hi = ""
        if present:
            try:
                if col.kind == "string":
                    lens = [len(str(v)) for v in present]
                    lo, hi = f"{min(lens)} tecken", f"{max(lens)} tecken"
                else:
                    lo, hi = _fmt(min(present)), _fmt(max(present))
            except TypeError:
                pass
        top = ", ".join(f"{_fmt(v)} ({c * 100 // max(len(present), 1)} %)" for v, c in counts.most_common(4)) if len(counts) < len(present) or len(counts) <= 4 else "alla unika"
        out.append({"Kolumn": name, "Typ": col.type_raw if col else "", "Andel NULL %": round((n - len(present)) * 100 / n, 1) if n else 0.0,
                    "Unika värden": len(counts), "Lägsta": lo, "Högsta": hi, "Vanligaste värden": top})
    return out


def relation_report(result: Result) -> list[dict]:
    """Kontrollerar varje relation: hur många barnrader som pekar på en förälder som inte finns."""
    out = []
    for key in result.order:
        data = result.data[key]
        for fk in data.table.foreign_keys:
            parent = data if fk.ref_table == key else result.data.get(fk.ref_table)
            if parent is None or any(c not in data.colidx for c in fk.columns) or any(c not in parent.colidx for c in fk.ref_columns):
                continue
            valid = {tuple(r[parent.colidx[c]] for c in fk.ref_columns) for r in parent.rows}
            keys = [tuple(r[data.colidx[c]] for c in fk.columns) for r in data.rows]
            filled = [k for k in keys if None not in k]
            used = len({k for k in filled if k in valid})
            out.append({"Tabell": key, "Relation": f"{', '.join(fk.columns)} → {fk.ref_table}", "Rader med värde": len(filled),
                        "Föräldralösa": sum(1 for k in filled if k not in valid),
                        "Föräldrar som används %": round(used * 100 / len(valid), 1) if valid else 0.0,
                        "Flest barn per förälder": max(Counter(filled).values()) if filled else 0})
    return out


def key_report(result: Result) -> list[dict]:
    out = []
    for key in result.order:
        data = result.data[key]
        t = data.table
        for u in [t.primary_key] + t.uniques:
            if u and all(c in data.colidx for c in u):
                keys = [k for k in (tuple(r[data.colidx[c]] for c in u) for r in data.rows) if None not in k]
                out.append({"Tabell": key, "Nyckel": " + ".join(u), "Rader": len(keys), "Dubbletter": len(keys) - len(set(keys))})
    return out
