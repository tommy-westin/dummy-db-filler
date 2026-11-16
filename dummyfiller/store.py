"""Lokal lagring av projekt i en SQLite-databas, med automatisk sparning och versionshistorik.

Databasen ligger i `data/dummyfiller.db` i repot (eller där miljövariabeln DUMMYFILLER_DB pekar). Den skapas
automatiskt och ignoreras av git, eftersom den innehåller varje utvecklares eget arbete. Projekt delas i stället
som YAML-filer.

- Projektets aktuella innehåll sparas efter varje ändring i gränssnittet.
- En ny version sparas när det gått en stund sedan förra versionen, så att historiken inte fylls med varje
  litet klick. Medan man arbetar uppdateras den senaste versionen.
- Om samma projekt har ändrats i en annan flik sparas den ändringen som en egen version innan den skrivs över,
  så att ingenting går förlorat.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .model import Project

VERSION_INTERVAL_S = 120  # minsta tid mellan två versioner i historiken
MAX_VERSIONS = 100  # per projekt; äldre versioner tas bort

_SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES project(id),
    saved_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    tables INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_version_project ON version(project_id, id);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_item (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
"""


def db_path() -> Path:
    env = os.environ.get("DUMMYFILLER_DB")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "data" / "dummyfiller.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # flera flikar kan läsa medan en skriver
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def serialize(project: Project) -> tuple[str, str]:
    """(innehåll som JSON, kontrollsumma). Kontrollsumman avgör om något ändrats sedan förra sparningen."""
    text = json.dumps(project.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
    return text, hashlib.sha1(text.encode("utf-8")).hexdigest()


def deserialize(text: str) -> Project:
    return Project.from_dict(json.loads(text))


def list_projects() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT p.id, p.name, p.updated_at, (SELECT COUNT(*) FROM version v WHERE v.project_id = p.id) AS versions "
                            "FROM project p WHERE p.deleted = 0 ORDER BY p.updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_setting(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO setting(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def load(project_id: int) -> tuple[Project, str] | None:
    """(projekt, kontrollsumma) eller None om projektet inte finns."""
    with _connect() as conn:
        row = conn.execute("SELECT content, hash FROM project WHERE id = ? AND deleted = 0", (project_id,)).fetchone()
    if row is None:
        return None
    set_setting("last_project", str(project_id))
    return deserialize(row["content"]), row["hash"]


def last_project_id() -> int | None:
    pid = get_setting("last_project")
    projects = list_projects()
    if pid and any(p["id"] == int(pid) for p in projects):
        return int(pid)
    return projects[0]["id"] if projects else None


def _add_version(conn, project_id: int, content: str, digest: str, note: str) -> None:
    tables = len(json.loads(content).get("tables") or [])
    conn.execute("INSERT INTO version(project_id, saved_at, note, tables, content, hash) VALUES (?, ?, ?, ?, ?, ?)",
                 (project_id, _now(), note, tables, content, digest))
    conn.execute("DELETE FROM version WHERE project_id = ? AND id NOT IN "
                 "(SELECT id FROM version WHERE project_id = ? ORDER BY id DESC LIMIT ?)", (project_id, project_id, MAX_VERSIONS))


def create(project: Project, note: str = "Skapat") -> tuple[int, str]:
    content, digest = serialize(project)
    with _connect() as conn:
        cur = conn.execute("INSERT INTO project(name, content, hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                           (project.name, content, digest, _now(), _now()))
        pid = cur.lastrowid
        _add_version(conn, pid, content, digest, note)
    set_setting("last_project", str(pid))
    return pid, digest


def save(project_id: int, project: Project, base_hash: str | None, note: str = "") -> str:
    """Sparar projektet. `base_hash` är kontrollsumman för det som den här fliken senast läste eller sparade.

    Returnerar den nya kontrollsumman.
    """
    content, digest = serialize(project)
    with _connect() as conn:
        row = conn.execute("SELECT content, hash FROM project WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        if row["hash"] == digest and not note:
            return digest
        if base_hash is not None and row["hash"] != base_hash and row["hash"] != digest:
            # någon annan flik har sparat under tiden: behåll den ändringen som en version innan den skrivs över
            _add_version(conn, project_id, row["content"], row["hash"], "Ändring från annan flik (ersatt)")
        conn.execute("UPDATE project SET name = ?, content = ?, hash = ?, updated_at = ? WHERE id = ?",
                     (project.name, content, digest, _now(), project_id))
        last = conn.execute("SELECT id, saved_at, note FROM version WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
        recent = last is not None and (datetime.now() - datetime.fromisoformat(last["saved_at"])).total_seconds() < VERSION_INTERVAL_S
        if note or not recent or last["note"]:
            _add_version(conn, project_id, content, digest, note)
        else:  # medan man arbetar: uppdatera senaste versionen i stället för att skapa en ny
            conn.execute("UPDATE version SET saved_at = ?, tables = ?, content = ?, hash = ? WHERE id = ?",
                         (_now(), len(project.tables), content, digest, last["id"]))
    return digest


def versions(project_id: int, limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, saved_at, note, tables FROM version WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                            (project_id, limit)).fetchall()
    return [dict(r) for r in rows]


def load_version(version_id: int) -> Project:
    with _connect() as conn:
        row = conn.execute("SELECT content FROM version WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        raise KeyError(version_id)
    return deserialize(row["content"])


# ---------------------------------------------------------------- generatorbiblioteket (se library.py)

def lib_items() -> list[tuple[str, str, object]]:
    with _connect() as conn:
        rows = conn.execute("SELECT kind, key, content FROM library_item ORDER BY kind, key").fetchall()
    return [(r["kind"], r["key"], json.loads(r["content"])) for r in rows]


def _bump(conn) -> None:
    conn.execute("INSERT INTO setting(key, value) VALUES ('library_rev', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)")


def lib_put(kind: str, key: str, content) -> None:
    text = json.dumps(content, ensure_ascii=False, default=str)
    with _connect() as conn:
        conn.execute("INSERT INTO library_item(kind, key, content, updated_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(kind, key) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
                     (kind, key, text, _now()))
        _bump(conn)


def lib_delete(kind: str, key: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM library_item WHERE kind = ? AND key = ?", (kind, key))
        _bump(conn)


def lib_revision() -> str:
    """Ändras varje gång biblioteket ändras (även från en annan flik eller process)."""
    return get_setting("library_rev") or "0"


# ---------------------------------------------------------------- logg över läsningar från produktion (se learn.py)

def audit_add(entry: dict) -> int:
    with _connect() as conn:
        cur = conn.execute("INSERT INTO audit(at, content) VALUES (?, ?)", (_now(), json.dumps(entry, ensure_ascii=False, default=str)))
        return cur.lastrowid


def audit_update(audit_id: int, extra: dict) -> None:
    with _connect() as conn:
        row = conn.execute("SELECT content FROM audit WHERE id = ?", (audit_id,)).fetchone()
        if row is not None:
            conn.execute("UPDATE audit SET content = ? WHERE id = ?",
                         (json.dumps({**json.loads(row["content"]), **extra}, ensure_ascii=False, default=str), audit_id))


def audit_list(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, at, content FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "at": r["at"], **json.loads(r["content"])} for r in rows]


def delete(project_id: int) -> None:
    """Markerar projektet som borttaget. Innehåll och versioner ligger kvar i databasen."""
    with _connect() as conn:
        conn.execute("UPDATE project SET deleted = 1, updated_at = ? WHERE id = ?", (_now(), project_id))
