"""Egna kolumnregler som återanvänds i alla projekt: 'kolumner som heter så här ska alltid genereras så här'.

Reglerna sparas i en YAML-fil i användarens hemkatalog (eller där miljövariabeln DUMMYFILLER_RULES pekar),
så att de kan delas i teamet. De prövas före de inbyggda tolkningsreglerna.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import yaml

_cache: tuple[float, list[dict]] | None = None


def rules_path() -> Path:
    return Path(os.environ.get("DUMMYFILLER_RULES") or Path.home() / ".dummyfiller" / "regler.yaml")


def load_rules() -> list[dict]:
    global _cache
    path = rules_path()
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _cache is None or _cache[0] != mtime:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError:
            data = []
        _cache = (mtime, [r for r in data if isinstance(r, dict) and r.get("pattern") and r.get("generator")])
    return _cache[1]


def save_rules(rules: list[dict]) -> None:
    global _cache
    path = rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _cache = None


def add_rule(pattern: str, generator: str, params: dict, kind: str = "", null_pct: float = 0.0) -> None:
    rules = [r for r in load_rules() if not (r["pattern"] == pattern and r.get("kind", "") == kind)]
    rules.insert(0, {"pattern": pattern, "kind": kind, "generator": generator, "params": dict(params), "null_pct": float(null_pct)})
    save_rules(rules)


def delete_rule(index: int) -> None:
    rules = list(load_rules())
    if 0 <= index < len(rules):
        rules.pop(index)
        save_rules(rules)


def match_rule(names: list[str], kind: str) -> dict | None:
    """Första regeln vars mönster (med * och ?) matchar något av namnen. `names` är kolumnnamnet i olika normaliseringar."""
    for r in load_rules():
        if r.get("kind") and r["kind"] != kind:
            continue
        pat = str(r["pattern"]).strip().lower()
        if any(fnmatch.fnmatchcase(n, pat) for n in names):
            return r
    return None
