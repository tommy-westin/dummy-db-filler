"""Tolerant tolk för CREATE TABLE / ALTER TABLE-skript (T-SQL, t.ex. skriptade från SSMS).

Allt som inte är tabell-, nyckel- eller relationsdefinitioner hoppas över.
"""
from __future__ import annotations

import re

from .model import Column, ForeignKey, Table

_IDENT = r'(?:\[[^\]]+\]|"[^"]+"|`[^`]+`|[\w@#$]+)'
_NAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT})*"


def _strip_comments(sql: str) -> str:
    def repl(m):
        return m.group(0) if m.group(0).startswith("'") else " "
    return re.sub(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", repl, sql, flags=re.S)


def _unquote(ident: str) -> str:
    ident = ident.strip()
    if len(ident) >= 2 and ident[0] in '["`':
        return ident[1:-1]
    return ident


def _split_name(name: str, default_schema: str) -> tuple[str, str]:
    parts = [_unquote(p) for p in re.findall(_IDENT, name)]
    return (parts[-2] if len(parts) > 1 else default_schema), parts[-1]


def _matching_paren(text: str, start: int) -> int:
    """Index för parentesen som stänger den som öppnas vid `start`."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            i = text.find("'", i + 1)
            if i == -1:
                return n - 1
        elif ch == "[":
            j = text.find("]", i)
            i = j if j != -1 else i
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def _split_top(body: str) -> list[str]:
    parts, depth, cur, i = [], 0, [], 0
    while i < len(body):
        ch = body[i]
        if ch == "'":
            j = body.find("'", i + 1)
            j = len(body) - 1 if j == -1 else j
            cur.append(body[i:j + 1])
            i = j + 1
            continue
        if ch == "[":
            j = body.find("]", i)
            j = i if j == -1 else j
            cur.append(body[i:j + 1])
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _paren_expr(text: str, start: int) -> str:
    """Innehållet i den parentes som börjar vid eller efter `start` ('' om ingen finns)."""
    i = text.find("(", start)
    if i == -1 or text[start:i].strip():
        return ""
    return text[i + 1:_matching_paren(text, i)].strip()


def _default_expr(tail: str) -> str | None:
    m = re.search(r"\bDEFAULT\b\s*", tail, re.I)
    if not m:
        return None
    rest = tail[m.end():]
    if rest.startswith("("):
        return rest[:_matching_paren(rest, 0) + 1]
    m2 = re.match(r"N?'(?:[^']|'')*'|[-\w.]+(?:\(\))?", rest)
    return m2.group(0) if m2 else None


def _col_list(text: str) -> list[str]:
    cols = []
    for part in _split_top(text):
        m = re.match(_IDENT, part.strip())
        if m:
            cols.append(_unquote(m.group(0)))
    return cols


_FK_RE = re.compile(rf"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+({_NAME})\s*(?:\(([^)]*)\))?", re.I)
_PK_RE = re.compile(r"PRIMARY\s+KEY(?:\s+(?:NON)?CLUSTERED)?\s*\(", re.I)
_UQ_RE = re.compile(r"UNIQUE(?:\s+(?:NON)?CLUSTERED)?\s*\(", re.I)
_CONSTRAINT_NAME = re.compile(rf"^\s*CONSTRAINT\s+({_IDENT})\s+", re.I)


def _table_constraint(item: str, table: Table, default_schema: str, pending_fks: list) -> bool:
    name = ""
    m = _CONSTRAINT_NAME.match(item)
    rest = item
    if m:
        name, rest = _unquote(m.group(1)), item[m.end():]
    head = rest.lstrip().upper()
    if head.startswith("PRIMARY KEY"):
        pm = _PK_RE.search(rest)
        if pm:
            end = _matching_paren(rest, pm.end() - 1)
            table.primary_key = _col_list(rest[pm.end():end])
        return True
    if head.startswith("UNIQUE"):
        um = _UQ_RE.search(rest)
        if um:
            end = _matching_paren(rest, um.end() - 1)
            table.uniques.append(_col_list(rest[um.end():end]))
        return True
    if head.startswith("FOREIGN KEY"):
        fm = _FK_RE.search(rest)
        if fm:
            pending_fks.append((table, name, _col_list(fm.group(1)), fm.group(2), _col_list(fm.group(3) or "")))
        return True
    if head.startswith("CHECK"):
        expr = _paren_expr(rest, rest.upper().find("CHECK") + 5)
        if expr:
            table.checks.append(expr)
        return True
    if head.startswith(("INDEX", "PERIOD FOR", "KEY ", "DEFAULT")):
        return True
    return bool(m)  # namngiven constraint av annat slag


def _column(item: str, table: Table, default_schema: str, pending_fks: list) -> None:
    m = re.match(rf"\s*({_IDENT})\s*(.*)$", item, re.S)
    if not m:
        return
    name, rest = _unquote(m.group(1)), m.group(2).strip()
    if not rest:
        return
    if re.match(r"AS\b|AS\(", rest, re.I):
        table.columns.append(Column(name=name, type_raw="computed", kind="other", computed=True))
        return
    tm = re.match(rf"((?:{_IDENT}\s*\.\s*)?{_IDENT}(?:\s+(?:varying|precision))?)\s*(\([^)]*\))?", rest, re.I)
    if not tm:
        return
    idents = [_unquote(p) for p in re.findall(_IDENT, tm.group(1))]
    base = idents[-1] if "." in tm.group(1) else " ".join(idents)  # [dbo].[MinTyp] -> MinTyp, double precision behålls
    type_raw = base + (re.sub(r"\s+", "", tm.group(2)) if tm.group(2) else "")
    tail = rest[tm.end():]
    upper = tail.upper()
    col = Column.from_type(name, type_raw)
    col.nullable = not re.search(r"\bNOT\s+NULL\b", upper)
    col.identity = bool(re.search(r"\bIDENTITY\b|\bAUTO_INCREMENT\b|\bAUTOINCREMENT\b", upper)) or type_raw.lower() in ("serial", "bigserial")
    if re.search(r"\bGENERATED\s+ALWAYS\b", upper):
        col.computed = True
    col.default = _default_expr(tail)
    cm = re.search(r"\bCHECK\b", tail, re.I)
    if cm:
        expr = _paren_expr(tail, cm.end())
        if expr:
            table.checks.append(expr)
    if re.search(r"\bPRIMARY\s+KEY\b", upper):
        table.primary_key = [name]
        col.nullable = False
    elif re.search(r"\bUNIQUE\b", upper):
        table.uniques.append([name])
    fm = re.search(rf"\bREFERENCES\s+({_NAME})\s*(?:\(([^)]*)\))?", tail, re.I)
    if fm:
        pending_fks.append((table, "", [name], fm.group(1), _col_list(fm.group(2) or "")))
    table.columns.append(col)


def parse_ddl(sql: str, default_schema: str = "dbo") -> tuple[list[Table], list[str]]:
    """Returnerar (tabeller, varningar)."""
    sql = _strip_comments(sql)
    tables: dict[str, Table] = {}
    warnings: list[str] = []
    pending_fks: list = []

    for m in re.finditer(rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({_NAME})\s*\(", sql, re.I):
        schema, name = _split_name(m.group(1), default_schema)
        if name.startswith("#"):
            continue
        open_idx = m.end() - 1
        close_idx = _matching_paren(sql, open_idx)
        table = Table(name=name, schema=schema)
        for item in _split_top(sql[open_idx + 1:close_idx]):
            if not item:
                continue
            if not _table_constraint(item, table, default_schema, pending_fks):
                _column(item, table, default_schema, pending_fks)
        if not table.columns:
            warnings.append(f"{table.key}: inga kolumner kunde tolkas")
            continue
        tables[f"{schema}.{name}".lower()] = table

    for m in re.finditer(rf"\bALTER\s+TABLE\s+(?:ONLY\s+)?({_NAME})(.*?)(?=;|\bGO\b|\bALTER\s+TABLE\b|\bCREATE\b|\Z)", sql, re.I | re.S):
        schema, name = _split_name(m.group(1), default_schema)
        table = tables.get(f"{schema}.{name}".lower())
        body = m.group(2)
        if table is None or not re.search(r"\bADD\b", body, re.I):
            continue
        for fm in _FK_RE.finditer(body):
            before = body[:fm.start()]
            cm = re.findall(rf"CONSTRAINT\s+({_IDENT})\s*$", before.rstrip() + " ", re.I)
            pending_fks.append((table, _unquote(cm[-1]) if cm else "", _col_list(fm.group(1)), fm.group(2), _col_list(fm.group(3) or "")))
        pm = _PK_RE.search(body)
        if pm:
            table.primary_key = _col_list(body[pm.end():_matching_paren(body, pm.end() - 1)])
        for um in _UQ_RE.finditer(body):
            table.uniques.append(_col_list(body[um.end():_matching_paren(body, um.end() - 1)]))
        for cm in re.finditer(r"\bCHECK\b(?!\s+CONSTRAINT)", body, re.I):
            expr = _paren_expr(body, cm.end())
            if expr:
                table.checks.append(expr)
        dm = re.search(rf"\bDEFAULT\b(.*?)\bFOR\s+({_IDENT})", body, re.I | re.S)
        if dm and (col := table.column(_unquote(dm.group(2)))) is not None:
            col.default = dm.group(1).strip()

    for table, name, cols, ref_name, ref_cols in pending_fks:
        rschema, rname = _split_name(ref_name, default_schema)
        ref = tables.get(f"{rschema}.{rname}".lower())
        ref_key = ref.key if ref else (f"{rschema}.{rname}" if rschema else rname)
        if not ref_cols and ref is not None:
            ref_cols = list(ref.primary_key)
        if not ref_cols or len(ref_cols) != len(cols):
            warnings.append(f"{table.key}: relationen till {ref_key} kunde inte tolkas fullständigt")
            continue
        if ref is None:
            warnings.append(f"{table.key}: refererar till {ref_key} som inte finns i skriptet")
        table.foreign_keys.append(ForeignKey(columns=cols, ref_table=ref_key, ref_columns=ref_cols, name=name))

    for table in tables.values():
        for c in table.primary_key:
            col = table.column(c)
            if col:
                col.nullable = False
    return list(tables.values()), warnings
