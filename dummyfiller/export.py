"""Export av genererad data till filer: CSV, Parquet och T-SQL-skript."""
from __future__ import annotations

import csv
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from .engine import Result, TableData


def _file_stem(data: TableData) -> str:
    return data.table.key.replace("/", "_").replace("\\", "_")


def write_csv(result: Result, folder: str | Path, delimiter: str = ";", encoding: str = "utf-8-sig") -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in result.order:
        data = result.data[key]
        path = folder / f"{_file_stem(data)}.csv"
        with path.open("w", newline="", encoding=encoding) as f:
            w = csv.writer(f, delimiter=delimiter)
            w.writerow(data.columns)
            for row in data.rows:
                w.writerow(["" if v is None else (int(v) if isinstance(v, bool) else v.hex() if isinstance(v, bytes) else v) for v in row])
        paths.append(path)
    return paths


def _arrow_type(col):
    import pyarrow as pa
    k = col.kind
    if k == "int":
        return pa.int64()
    if k == "decimal":
        return pa.decimal128(min(col.precision or 18, 38), col.scale or 0)
    if k == "float":
        return pa.float64()
    if k == "bool":
        return pa.bool_()
    if k == "date":
        return pa.date32()
    if k == "datetime":
        return pa.timestamp("us")
    if k == "time":
        return pa.time64("us")
    if k == "binary":
        return pa.binary()
    return pa.string()


def write_parquet(result: Result, folder: str | Path) -> list[Path]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in result.order:
        data = result.data[key]
        arrays, names = [], []
        for i, name in enumerate(data.columns):
            col = data.table.column(name)
            arrays.append(pa.array([r[i] for r in data.rows], type=_arrow_type(col)))
            names.append(name)
        path = folder / f"{_file_stem(data)}.parquet"
        pq.write_table(pa.Table.from_arrays(arrays, names=names), path)
        paths.append(path)
    return paths


def sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.isoformat(sep='T', timespec='seconds')}'"
    if isinstance(v, (date, time)):
        return f"'{v.isoformat()}'"
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex()
    return "N'" + str(v).replace("'", "''") + "'"


def _qname(data: TableData) -> str:
    t = data.table
    name = "[" + t.name.replace("]", "]]") + "]"
    return f"[{t.schema}].{name}" if t.schema else name


def write_sql(result: Result, path: str | Path, empty_first: bool = False, batch_size: int = 500) -> Path:
    """Ett T-SQL-skript med INSERT-satser i beroendeordning."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        f.write("-- Genererad dummy-data (dummyfiller). Tabellerna laddas i beroendeordning.\nSET NOCOUNT ON;\n")
        if empty_first:
            f.write("\n-- Töm tabellerna (barn före föräldrar)\n")
            for key in reversed(result.order):
                f.write(f"DELETE FROM {_qname(result.data[key])};\n")
        for key in result.order:
            data = result.data[key]
            if not data.rows:
                continue
            qn = _qname(data)
            identity = any(c.identity for c in data.table.columns if c.name in data.colidx)
            cols = ", ".join("[" + c.replace("]", "]]") + "]" for c in data.columns)
            f.write(f"\n-- {data.table.key}: {len(data.rows)} rader\n")
            if identity:
                f.write(f"SET IDENTITY_INSERT {qn} ON;\n")
            for start in range(0, len(data.rows), batch_size):
                f.write(f"INSERT INTO {qn} ({cols}) VALUES\n")
                chunk = data.rows[start:start + batch_size]
                f.write(",\n".join("(" + ", ".join(sql_literal(v) for v in row) + ")" for row in chunk))
                f.write(";\n")
            if identity:
                f.write(f"SET IDENTITY_INSERT {qn} OFF;\n")
            f.write("GO\n")
    return path
