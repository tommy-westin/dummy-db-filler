"""Redigering av projektets struktur: byta namn, ta bort, koppla ihop tabeller och placera dem i diagrammet.

Funktionerna håller ihop allt som hänger på ett namn (nycklar, relationer, historik, generatorparametrar),
så att gränssnittet kan låta användaren ändra fritt utan att projektet blir inkonsekvent.
"""
from __future__ import annotations

import re

from .generators import REGISTRY
from .model import ForeignKey, Project, Table

NODE_WIDTH, COL_GAP, ROW_GAP = 318, 110, 34


def node_height(table: Table) -> int:
    return 58 + 24 * len(table.columns) + 30


def auto_layout(project: Project, only_missing: bool = True) -> None:
    """Placerar tabellerna i kolumner efter beroenden: föräldrar till vänster, barn till höger."""
    targets = [t for t in project.tables if not (only_missing and len(t.pos) == 2)]
    if not targets:
        return
    depth: dict[str, int] = {}

    def level(t: Table, seen: frozenset) -> int:
        if t.key in depth:
            return depth[t.key]
        parents = [p for fk in t.foreign_keys if (p := project.table(fk.ref_table)) is not None and p.key != t.key and p.key not in seen]
        d = 1 + max((level(p, seen | {t.key}) for p in parents), default=-1)
        depth[t.key] = d
        return d

    for t in project.tables:
        level(t, frozenset())
    bottoms: dict[int, float] = {}
    for t in project.tables:  # redan placerade tabeller tar plats i sin kolumn
        if t not in targets:
            d = round(t.pos[0] / (NODE_WIDTH + COL_GAP))
            bottoms[d] = max(bottoms.get(d, 0), t.pos[1] + node_height(t) + ROW_GAP)
    for t in sorted(targets, key=lambda x: (depth[x.key], -len(x.foreign_keys), x.name.lower())):
        d = depth[t.key]
        y = bottoms.get(d, 0)
        t.pos = [d * (NODE_WIDTH + COL_GAP), y]
        bottoms[d] = y + node_height(t) + ROW_GAP


def _swap(values: list[str], old: str, new: str) -> list[str]:
    return [new if v == old else v for v in values]


def rename_column(project: Project, table: Table, old: str, new: str) -> None:
    col = table.column(old)
    if col is None or old == new:
        return
    if table.column(new) is not None:
        raise ValueError(f"Kolumnen {new} finns redan i {table.key}.")
    col.name = new
    table.primary_key = _swap(table.primary_key, old, new)
    table.uniques = [_swap(u, old, new) for u in table.uniques]
    for fk in table.foreign_keys:
        fk.columns = _swap(fk.columns, old, new)
    h = table.history
    if h:
        for k in ("from", "to", "current"):
            if h.get(k) == old:
                h[k] = new
        h["changing"] = _swap(h.get("changing") or [], old, new)
    word = re.compile(r"(?<![\w'])" + re.escape(old) + r"(?![\w'])")
    for t in project.tables:
        for fk in t.foreign_keys:
            if fk.ref_table == table.key:
                fk.ref_columns = _swap(fk.ref_columns, old, new)
        for c in t.columns:
            spec = REGISTRY.get(c.generator)
            if not spec or not c.params:
                continue
            for p in spec.params:
                v = c.params.get(p.name)
                if v != old and p.name not in ("expr", "template"):
                    continue
                if t is table and p.type in ("column", "fk"):
                    c.params[p.name] = new
                elif p.type == "parent_column":  # pekar på en kolumn i föräldratabellen
                    fk = t.fk_for(c.params.get(p.via, ""))
                    if fk is not None and fk.ref_table == table.key:
                        c.params[p.name] = new
                elif t is table and p.name == "expr" and isinstance(v, str):
                    c.params[p.name] = word.sub(new, v).replace(f"col('{old}')", f"col('{new}')")
                elif t is table and p.name == "template" and isinstance(v, str):
                    c.params[p.name] = v.replace("{" + old + "}", "{" + new + "}")


def rename_table(project: Project, table: Table, name: str, schema: str) -> None:
    old = table.key
    new = f"{schema}.{name}" if schema else name
    if new == old:
        return
    if project.table(new) is not None:
        raise ValueError(f"Tabellen {new} finns redan.")
    table.name, table.schema = name, schema
    for t in project.tables:
        for fk in t.foreign_keys:
            if fk.ref_table == old:
                fk.ref_table = table.key
    if project.dirty.get("tables"):
        project.dirty["tables"] = _swap(project.dirty["tables"], old, table.key)


def delete_column(project: Project, table: Table, name: str) -> None:
    table.columns = [c for c in table.columns if c.name != name]
    table.primary_key = [c for c in table.primary_key if c != name]
    table.uniques = [u for u in table.uniques if name not in u]
    table.foreign_keys = [fk for fk in table.foreign_keys if name not in fk.columns]
    for t in project.tables:  # relationer som pekade på kolumnen
        t.foreign_keys = [fk for fk in t.foreign_keys if not (fk.ref_table == table.key and name in fk.ref_columns)]
    if table.history and name in (table.history.get("from"), table.history.get("to")):
        table.history = {}


def is_key(table: Table, column: str) -> bool:
    return table.primary_key == [column] or [column] in table.uniques


def connect(project: Project, a_key: str, a_col: str, b_key: str, b_col: str, flip: bool = True) -> tuple[str, str, ForeignKey | None]:
    """Skapar en relation mellan två kolumner. Returnerar (nivå, meddelande, relation).

    Pilen dras normalt från barnets kolumn till förälderns nyckel. Dras den åt andra hållet (från en nyckel till en
    vanlig kolumn) vänds den automatiskt, så att nyckeln alltid blir förälder.
    """
    a, b = project.table(a_key), project.table(b_key)
    if a is None or b is None or a.column(a_col) is None or b.column(b_col) is None:
        return "error", "Kolumnen finns inte längre.", None
    if a is b:
        if is_key(a, a_col) and not is_key(a, b_col):
            a_col, b_col = b_col, a_col
    elif flip and is_key(a, a_col) and not is_key(b, b_col):
        a, b, a_col, b_col = b, a, b_col, a_col
    child, parent, ccol, pcol = a, b, a.column(a_col), b.column(b_col)
    if ccol.computed or pcol.computed:
        return "error", "Kolumner som sätts av databasen kan inte ingå i en relation.", None
    if ccol.kind != pcol.kind:
        return "error", f"{child.name}.{ccol.name} ({ccol.type_raw}) och {parent.name}.{pcol.name} ({pcol.type_raw}) har olika datatyp och kan inte kopplas ihop.", None
    existing = child.fk_for(ccol.name)
    if existing is not None:
        if existing.ref_table == parent.key and existing.ref_columns == [pcol.name]:
            return "info", "Relationen finns redan.", existing
        return "error", f"{child.name}.{ccol.name} pekar redan på {existing.ref_table}. Ta bort den relationen först.", None
    fk = ForeignKey(columns=[ccol.name], ref_table=parent.key, ref_columns=[pcol.name], source="manual")
    child.foreign_keys.append(fk)
    msg = f"Relation skapad: {child.name}.{ccol.name} → {parent.name}.{pcol.name}."
    if not is_key(parent, pcol.name):
        return "warning", msg + f" Obs: {pcol.name} är varken primärnyckel eller unik i {parent.name}.", fk
    return "success", msg, fk
