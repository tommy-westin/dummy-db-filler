"""Avsiktligt smutsig data: efterliknar kvalitetsproblem i källsystem så att integrationer kan testas mot dem.

Nyckelkolumner (PK, unika, FK och kolumner som andra tabeller pekar på) rörs aldrig, så datan går fortfarande att ladda.
Undantaget är 'föräldralösa nycklar', som bara tillämpas på egna relationer – de som inte är deklarerade i databasen.
"""
from __future__ import annotations

import random
from collections import Counter

KINDS = {
    "whitespace": "Blanksteg före eller efter text",
    "case": "Blandade versaler och gemener",
    "empty": "Tom sträng i stället för NULL",
    "format": "Varierande format (utan mellanslag och bindestreck)",
    "duplicates": "Dubbletter (samma uppgifter på flera rader)",
    "orphans": "Föräldralösa nycklar (endast egna relationer)",
}


def apply_dirty(project, result) -> None:
    cfg = project.dirty or {}
    pct = float(cfg.get("pct", 3))
    kinds = [k for k in (cfg.get("kinds") or list(KINDS)) if k in KINDS]
    tables = set(cfg.get("tables") or [])
    if pct <= 0 or not kinds:
        return
    rng = random.Random(f"{project.seed}:dirty")
    referenced = {(fk.ref_table, c) for t in project.tables for fk in t.foreign_keys for c in fk.ref_columns}
    for key in result.order:
        if key not in tables:
            continue
        data = result.data[key]
        t, rows = data.table, data.rows
        if not rows:
            continue
        protected = set(t.primary_key) | {c for u in t.uniques for c in u} | {c for fk in t.foreign_keys for c in fk.columns}
        protected |= {c for k, c in referenced if k == key}
        text = [c for c in t.columns if c.name in data.colidx and c.kind == "string" and c.name not in protected]
        k = max(1, round(len(rows) * pct / 100))
        done: Counter = Counter()
        for kind in kinds:
            if kind in ("whitespace", "case", "empty", "format") and text:
                for _ in range(k):
                    row, col = rng.choice(rows), rng.choice(text)
                    i = data.colidx[col.name]
                    v = row[i]
                    new = v
                    if kind == "empty":
                        new = "" if v is None and col.nullable else v
                    elif isinstance(v, str) and v:
                        if kind == "whitespace":
                            new = rng.choice([" " + v, v + " ", v + "  ", "  " + v])
                            if col.length and len(new) > col.length:
                                new = v
                        elif kind == "case":
                            new = rng.choice([v.upper(), v.lower()])
                        elif kind == "format" and any(ch.isdigit() for ch in v):
                            new = v.replace(" ", "").replace("-", "")
                    if new != v:
                        row[i] = new
                        done[kind] += 1
            elif kind == "duplicates":
                free = [data.colidx[c.name] for c in t.columns if c.name in data.colidx and c.name not in protected]
                has_keys = bool(t.primary_key or t.uniques)
                for _ in range(k):
                    if not has_keys:
                        rows.append(list(rng.choice(rows)))
                        done[kind] += 1
                    elif free and len(rows) > 1:
                        src, dst = rng.sample(rows, 2)
                        for i in free:
                            dst[i] = src[i]
                        done[kind] += 1
            elif kind == "orphans":
                for fk in t.foreign_keys:
                    cols = [t.column(c) for c in fk.columns]
                    if fk.source != "manual" or any(c is None or c.name in t.primary_key or c.name not in data.colidx for c in cols):
                        continue
                    if any(c.name in u for c in cols for u in t.uniques):
                        continue
                    for n in range(k):
                        row = rng.choice(rows)
                        for c in cols:
                            i = data.colidx[c.name]
                            if c.kind == "int":
                                row[i] = 900000000 + rng.randint(0, 99999)
                            elif c.kind == "string":
                                row[i] = f"SAKNAS{n}"[: c.length or 20]
                        done[kind] += 1
        for kind, n in done.items():
            result.dirty_log.append(f"{key}: {n} × {KINDS[kind].lower()}")
