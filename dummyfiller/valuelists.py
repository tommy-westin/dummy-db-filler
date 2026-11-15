"""Inläsning av exempelfiler (text eller CSV) till projektets värdelistor."""
from __future__ import annotations

import csv
import io

MAX_VALUES = 20000


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_file(filename: str, raw: bytes | str, has_header: bool | None = None) -> dict[str, list[str]]:
    """Textfil med ett värde per rad -> en lista med filens namn.

    CSV/TSV med flera kolumner -> en lista per kolumn, namngiven 'fil:kolumn'. Listor från samma fil är lika
    långa och radvis ordnade, så att generatorn kan hålla ihop värden från samma exempelrad.
    """
    text = decode(raw) if isinstance(raw, bytes) else raw
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}
    delimiter = None
    if filename.lower().endswith((".csv", ".tsv")) or any(d in lines[0] for d in (";", "\t")):
        counts = {d: lines[0].count(d) for d in (";", "\t", ",", "|")}
        best = max(counts, key=counts.get)
        if counts[best] > 0:
            delimiter = best
    if delimiter is None:
        return {stem: [ln.strip() for ln in lines][:MAX_VALUES]}
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    width = max(len(r) for r in rows)
    if has_header is None:
        has_header = not any(_looks_numeric(c) for c in rows[0]) and len(rows) > 1
    header = [h.strip() or f"kolumn{i + 1}" for i, h in enumerate(rows[0])] if has_header else []
    header += [f"kolumn{i + 1}" for i in range(len(header), width)]
    body = rows[1:] if has_header else rows
    out = {}
    for i, name in enumerate(header):
        out[f"{stem}:{name}"] = [(r[i].strip() if i < len(r) else "") for r in body][:MAX_VALUES]
    return out


def _looks_numeric(s: str) -> bool:
    try:
        float(s.strip().replace(",", ".").replace(" ", ""))
        return True
    except ValueError:
        return False
