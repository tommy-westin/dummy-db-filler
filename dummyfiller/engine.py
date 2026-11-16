"""Genereringsmotorn: laddordning, primär-/främmande nycklar, unika värden och typanpassning."""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import prod
from typing import Callable

from faker import Faker

from .generators import REGISTRY, defaults
from .model import Column, ForeignKey, Project, Table, int_range

MAX_ATTEMPTS = 200
UNSCALED = ("reference", "calendar")  # kategorier vars radantal inte skalas med scenario
HISTORY_AUTO = ("address.", "phone", "choice", "person.email", "company.email", "number.", "list", "care.unit", "care.clinic")


@dataclass
class TableData:
    table: Table
    columns: list[str]
    rows: list[list] = field(default_factory=list)

    def __post_init__(self):
        self.colidx = {c: i for i, c in enumerate(self.columns)}
        self._index: dict = {}

    def column_values(self, name: str) -> list:
        i = self.colidx[name]
        return [r[i] for r in self.rows]

    def find(self, cols: list[str], values: tuple):
        """Slår upp en rad på nyckelvärden (med cache)."""
        key = tuple(cols)
        if key not in self._index:
            if any(c not in self.colidx for c in cols):
                return None
            idx = [self.colidx[c] for c in cols]
            self._index[key] = {tuple(r[i] for i in idx): r for r in self.rows}
        return self._index[key].get(tuple(values))


@dataclass
class Append:
    """Inkrementell körning: nya rader ovanpå data som redan finns i databasen."""
    existing: dict[str, TableData] = field(default_factory=dict)  # tabeller som inte får nya rader (används som föräldrar)
    counts: dict[str, int] = field(default_factory=dict)  # befintligt radantal per tabell som får nya rader
    maxima: dict[str, dict[str, int]] = field(default_factory=dict)  # högsta befintliga värde per heltalskolumn
    existing_keys: dict[str, dict[tuple, set]] = field(default_factory=dict)  # befintliga unika nycklar
    new_tables: set[str] = field(default_factory=set)
    since: date | None = None  # nya rader får datum från och med detta
    fraction: float = 1.0  # andel av tabellens radantal som genereras


@dataclass
class Result:
    data: dict[str, TableData] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # tabeller som ska skrivas, i laddordning
    warnings: list[str] = field(default_factory=list)
    existing: set[str] = field(default_factory=set)  # tabeller som lästs från databasen och inte skrivs
    dirty_log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- typanpassning

def coerce(value, col: Column):
    """Anpassar ett genererat värde till kolumnens datatyp (längd, skala, intervall)."""
    if value is None:
        return None
    k = col.kind
    try:
        if k == "string" or k == "other":
            if isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, (date, datetime, time)):
                value = value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
            elif isinstance(value, float) and value.is_integer():
                value = str(int(value))
            s = str(value)
            if col.length and len(s) > col.length:
                compact = s.replace(" ", "")
                s = compact if len(compact) <= col.length and len(s) <= 20 else s[: col.length].rstrip()
            return s
        if k == "int":
            if isinstance(value, str):
                digits = "".join(ch for ch in value if ch.isdigit())
                if not digits:
                    return None
                value = int(digits) * (-1 if value.strip().startswith("-") else 1)
            elif isinstance(value, (date, datetime)):
                value = value.year * 10000 + value.month * 100 + value.day
            lo, hi = int_range(col.type_raw)
            return max(lo, min(hi, int(round(value))))
        if k == "decimal":
            if isinstance(value, str):
                value = value.replace(" ", "").replace(",", ".")
            scale = col.scale or 0
            d = Decimal(str(float(value)) if isinstance(value, float) else str(int(value) if isinstance(value, bool) else value))
            d = d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
            if col.precision:
                limit = Decimal(10) ** (col.precision - scale) - Decimal(1).scaleb(-scale)
                d = max(-limit, min(limit, d))
            return d
        if k == "float":
            return float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
        if k == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "sant", "ja", "j", "y", "yes")
            return bool(value)
        if k == "date":
            if isinstance(value, datetime):
                return value.date()
            return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        if k == "datetime":
            if isinstance(value, datetime):
                return value.replace(microsecond=0)
            if isinstance(value, date):
                return datetime.combine(value, time())
            return datetime.fromisoformat(str(value))
        if k == "time":
            if isinstance(value, datetime):
                return value.time()
            return value if isinstance(value, time) else time.fromisoformat(str(value))
        if k == "uuid":
            return str(value)
        if k == "binary":
            return value if isinstance(value, (bytes, bytearray)) else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None
    return value


# ---------------------------------------------------------------- laddordning

def load_order(project: Project, keys: list[str]) -> tuple[list[str], list[tuple[str, ForeignKey]]]:
    """Topologisk sortering: föräldrar före barn. Cirkulära relationer bryts (helst vid en NULL-bar FK)."""
    tables = {k: project.table(k) for k in keys}
    broken: list[tuple[str, ForeignKey]] = []
    deps = {
        k: [fk for fk in t.foreign_keys if fk.ref_table in tables and fk.ref_table != k]
        for k, t in tables.items()
    }
    order: list[str] = []
    remaining = list(keys)
    while remaining:
        ready = [k for k in remaining if not any(fk.ref_table in remaining for fk in deps[k])]
        if ready:
            order += ready
            remaining = [k for k in remaining if k not in ready]
            continue
        candidates = [(k, fk) for k in remaining for fk in deps[k] if fk.ref_table in remaining]

        def nullable(item):
            t = tables[item[0]]
            return all((c := t.column(n)) is not None and c.nullable for n in item[1].columns)

        pick = next((c for c in candidates if nullable(c)), candidates[0])
        deps[pick[0]].remove(pick[1])
        broken.append(pick)
    return order, broken


def estimated_rows(project: Project, table: Table, scale: float = 1.0, _seen: frozenset = frozenset()) -> int:
    """Ungefärligt radantal, med hänsyn till 'barn per förälder' och scenario."""
    for fk in table.foreign_keys:
        parent = project.table(fk.ref_table)
        if fk.per_parent_max > 0 and parent is not None and parent.key != table.key and parent.key not in _seen:
            avg = (max(0, fk.per_parent_min) + fk.per_parent_max) / 2
            return round(estimated_rows(project, parent, scale, _seen | {table.key}) * avg)
    if table.history.get("enabled"):
        avg = (int(table.history.get("min", 1)) + int(table.history.get("max", 3))) / 2
    else:
        avg = 1
    n = table.rows if table.category in UNSCALED else max(1, round(table.rows * scale)) if table.rows else 0
    return round(n * avg)


# ---------------------------------------------------------------- radkontext

class RowContext:
    """Det generatorerna ser: slump, Faker, radens övriga värden och relaterade föräldrarader."""

    def __init__(self, tg: "_TableGen"):
        self._tg = tg
        self.rng = tg.rng
        self.fake = tg.fake
        self.table = tg.table
        self.project = tg.project
        self.locale = tg.project.locale
        self.today = tg.today
        self.since = tg.append.since if tg.append else None
        self.shared = tg.shared
        self.seed = tg.project.seed
        self.n_rows = tg.n
        self.index = 0
        self.column: Column | None = None
        self.state: dict = {}
        self.values: dict = {}
        self.parents: dict = {}
        self._entities: dict = {}
        self._resolving: set = set()

    def reset(self, index: int):
        self.index = index
        self.values, self.parents, self._entities, self._resolving = {}, {}, {}, set()

    @property
    def offset(self) -> int:
        """Förskjutning för löpnummer vid inkrementell körning (fortsätter efter befintliga rader)."""
        return self._tg.offsets.get(self.column.name if self.column else "", self._tg.count_offset)

    def has_column(self, name: str) -> bool:
        return name in self._tg.cols

    def get(self, name: str):
        if name in self.values:
            return self.values[name]
        return self._tg.resolve(self, name)

    def entity(self, key: str, build: Callable):
        if key not in self._entities:
            self._entities[key] = build()
        return self._entities[key]

    def table_data(self, key: str) -> TableData | None:
        return self._tg.result.data.get(key)

    def parent_ref(self, via: str):
        """(föräldratabellens data, radindex) för en FK-kolumn, eller None."""
        if not via:
            return None
        if via not in self.parents and via in self._tg.cols and via not in self.values:
            self.get(via)
        return self.parents.get(via)

    def parent_seq(self, via: str) -> int | None:
        """Hur många rader samma förälder redan har fått (0 för den första)."""
        ref = self.parent_ref(via)
        if ref is None:
            return None
        return self._tg.seq_counts.get(via, {}).get(ref[1], 0)

    def parent_value(self, via: str, column: str):
        if via not in self.parents and self.parent_ref(via) is None and via not in self.parents:
            raise ValueError(f"'{via}' är inte en främmande nyckel med genererad föräldratabell")
        ref = self.parents[via]
        if ref is None:
            return None
        data, idx = ref
        if column not in data.colidx:
            raise ValueError(f"kolumnen '{column}' finns inte i {data.table.key}")
        return data.rows[idx][data.colidx[column]]


class _FkPlan:
    def __init__(self, fk: ForeignKey, parent: TableData | None, is_self: bool, unique: bool, nullable: bool, rng):
        self.fk, self.parent, self.is_self, self.unique, self.nullable = fk, parent, is_self, unique, nullable
        self.perm: list[int] = []
        self.assign: list[int] | None = None  # barn per förälder: förälderindex per rad
        self.keymap: dict | None = None  # styrd relation: nyckelvärde -> radindex i föräldern
        if parent is not None and not is_self:
            self.perm = list(range(len(parent.rows)))
            rng.shuffle(self.perm)


class _TableGen:
    def __init__(self, project: Project, table: Table, n: int, result: Result, broken: set, fake: Faker, today: date,
                 append: Append | None = None, max_rows: int | None = None):
        self.project, self.table, self.result, self.today, self.append = project, table, result, today, append
        self.max_rows = max_rows
        seed = project.seed
        self.rng = random.Random(f"{seed}:{table.key}")
        fake.seed_instance(zlib.crc32(f"{seed}:{table.key}".encode()))
        self.fake = fake
        self.cols = {c.name: c for c in table.columns if not c.computed}
        self.out_cols = list(self.cols)
        self.params = {c.name: {**defaults(c.generator), **(c.params or {})} for c in self.cols.values()}
        self.states: dict[str, dict] = {c: {} for c in self.cols}
        self.pk = set(table.primary_key)
        self.unique_sets = [u for u in ([table.primary_key] + table.uniques) if u and all(c in self.cols for c in u)]
        self._warned: set = set()
        self.plans: list[_FkPlan] = []
        self.fk_cols: set[str] = set()
        self.deferred_cols: set[str] = set()
        self.seq_counts: dict[str, dict[int, int]] = {}
        self.shared: dict = {}  # delat tillstånd för generatorer i tabellen
        self.n = n
        self.count_offset = 0
        self.offsets: dict[str, int] = {}
        if append and table.key in append.new_tables:
            self.count_offset = append.counts.get(table.key, 0)
            for name, mx in append.maxima.get(table.key, {}).items():
                col = self.cols.get(name)
                if col is not None and col.generator == "sequence" and mx is not None:
                    p = self.params[name]
                    start, step = int(p["start"]), int(p["step"]) or 1
                    self.offsets[name] = max(0, (int(mx) - start) // step + 1)
        self._plan_fks(broken)

    def warn(self, msg: str, once_key=None):
        key = once_key or msg
        if key in self._warned:
            return
        self._warned.add(key)
        self.result.warnings.append(f"{self.table.key}: {msg}")

    def _plan_fks(self, broken: set):
        t = self.table
        product_sizes = []
        driver = None
        for fk in t.foreign_keys:
            if not fk.columns or any(c not in self.cols for c in fk.columns):
                continue
            if id(fk) in broken:
                self.deferred_cols.update(fk.columns)
                continue
            if self.fk_cols & set(fk.columns):
                self.warn(f"relationen till {fk.ref_table} delar kolumn med en annan relation och hoppas över")
                continue
            is_self = fk.ref_table == t.key
            parent = None if is_self else self.result.data.get(fk.ref_table)
            ref_table = t if is_self else (parent.table if parent else None)
            if ref_table is None:
                self.warn(f"föräldratabellen {fk.ref_table} genereras inte – {', '.join(fk.columns)} fylls med vanliga värden i stället")
                continue
            if len(fk.ref_columns) != len(fk.columns) or any(ref_table.column(c) is None for c in fk.ref_columns) \
                    or (parent is not None and any(c not in parent.colidx for c in fk.ref_columns)):
                self.warn(f"relationen till {fk.ref_table} pekar på kolumner som saknas och hoppas över")
                continue
            nullable = all(self.cols[c].nullable for c in fk.columns)
            unique = fk.distribution == "unique" or any(set(u) <= set(fk.columns) for u in self.unique_sets)
            plan = _FkPlan(fk, parent, is_self, unique, nullable, self.rng)
            if fk.guided and not is_self and not unique and len(fk.columns) == 1 and self.cols[fk.columns[0]].generator in REGISTRY:
                i = parent.colidx[fk.ref_columns[0]]
                plan.keymap = {r[i]: n for n, r in enumerate(parent.rows)}
            self.plans.append(plan)
            self.fk_cols.update(fk.columns)
            counts: dict[int, int] = {}
            for c in fk.columns:
                self.seq_counts[c] = counts
            if is_self:
                continue
            size = len(parent.rows)
            product_sizes.append(size)
            if fk.per_parent_max > 0 and not unique and driver is None and size > 0:
                driver = plan
                lo, hi = sorted((max(0, fk.per_parent_min), fk.per_parent_max))
                plan.assign = [idx for idx in range(size) for _ in range(self.rng.randint(lo, hi))]
                self.n = len(plan.assign) if self.max_rows is None else min(len(plan.assign), self.max_rows)
                if self.max_rows is not None:  # förhandsgranskning: visa hela syskonskaror i början
                    plan.assign = plan.assign[: self.n]
            elif size == 0 and not nullable:
                self.warn(f"föräldratabellen {fk.ref_table} är tom – inga rader kan skapas")
                self.n = 0
            elif unique and self.n > size and not (nullable and fk.null_pct > 0):
                self.warn(f"{self.n} rader begärdes men relationen till {fk.ref_table} är en-till-en med {size} föräldrarader – antalet sänks")
                self.n = size
        self.plans.sort(key=lambda p: p.keymap is not None)  # styrda relationer sist: de kan bero på radens övriga föräldrar
        if len(self.plans) > 1 and product_sizes:
            for u in self.unique_sets:
                if set(u) <= self.fk_cols:
                    sizes = [len(p.parent.rows) for p in self.plans if not p.is_self and set(p.fk.columns) & set(u)]
                    cap = prod(sizes) if sizes else self.n
                    if self.n > cap:
                        self.warn(f"{self.n} rader begärdes men det finns bara {cap} unika kombinationer av föräldrar – antalet sänks")
                        self.n = cap

    # ---- en rad ----
    def _fill_fks(self, ctx: RowContext, rows: list[list], attempt: int, slot: int):
        i, rng = slot, self.rng
        for plan in self.plans:
            fk = plan.fk
            if fk.columns[0] in ctx.values:  # redan satt (historik: samma förälder som föregående version)
                continue
            idx = None
            if plan.is_self:
                n_prev = len(rows)
                if n_prev > 0 and not (plan.nullable and rng.random() * 100 < fk.null_pct):
                    idx = int(n_prev * rng.random() ** 2)
                elif not plan.nullable:
                    idx = -1  # första raden pekar på sig själv
            else:
                m = len(plan.perm)
                if plan.assign is not None:
                    idx = plan.assign[i] if i < len(plan.assign) else plan.perm[rng.randrange(m)]
                elif plan.keymap is not None and m and not (plan.nullable and fk.null_pct > 0 and rng.random() * 100 < fk.null_pct):
                    col = self.cols[fk.columns[0]]
                    prev = (ctx.column, ctx.state)
                    ctx.column, ctx.state = col, self.states[col.name]
                    try:
                        wanted = coerce(REGISTRY[col.generator].func(ctx, self.params[col.name]), self.cols[fk.columns[0]])
                    except Exception:
                        wanted = None
                    finally:
                        ctx.column, ctx.state = prev
                    idx = plan.keymap.get(wanted)
                    if idx is None:
                        idx = plan.perm[rng.randrange(m)]
                elif m == 0 or (plan.nullable and fk.null_pct > 0 and rng.random() * 100 < fk.null_pct):
                    idx = None
                elif plan.unique:
                    idx = plan.perm[i] if i < m else None
                    if idx is None and not plan.nullable:
                        idx = plan.perm[i % m]
                elif fk.distribution == "even":
                    idx = plan.perm[(i + attempt) % m]
                elif fk.distribution == "skewed":
                    idx = plan.perm[int(m * rng.random() ** 1.5)]
                else:
                    idx = plan.perm[rng.randrange(m)]
            if idx is None:
                for c in fk.columns:
                    ctx.values[c] = None
                    ctx.parents[c] = None
            elif idx == -1:
                for c, rc in zip(fk.columns, fk.ref_columns):
                    ctx.values[c] = ctx.get(rc)
                    ctx.parents[c] = None
            else:
                if plan.is_self:
                    prow, colidx, ref = rows[idx], self._self_data.colidx, (self._self_data, idx)
                else:
                    prow, colidx, ref = plan.parent.rows[idx], plan.parent.colidx, (plan.parent, idx)
                for c, rc in zip(fk.columns, fk.ref_columns):
                    ctx.values[c] = coerce(prow[colidx[rc]], self.cols[c])
                    ctx.parents[c] = ref

    def resolve(self, ctx: RowContext, name: str):
        col = self.cols.get(name)
        if col is None:
            raise ValueError(f"okänd kolumn '{name}'")
        if name in ctx._resolving:
            raise ValueError(f"cirkulärt beroende via kolumnen '{name}'")
        ctx._resolving.add(name)
        prev = (ctx.column, ctx.state)
        ctx.column, ctx.state = col, self.states[name]
        try:
            if col.nullable and name not in self.pk and col.null_pct > 0 and self.rng.random() * 100 < col.null_pct:
                value = None
            else:
                spec = REGISTRY.get(col.generator)
                if spec is None:
                    self.warn(f"kolumnen {name} saknar generator och blir NULL", ("nogen", name))
                    value = None
                else:
                    try:
                        value = coerce(spec.func(ctx, self.params[name]), col)
                    except Exception as e:  # ett fel i en generator ska inte stoppa hela körningen
                        self.warn(f"kolumnen {name} ({spec.label}): {e}", ("err", name))
                        value = None
                if value is None and not col.nullable and col.generator != "null":
                    self.warn(f"kolumnen {name} är NOT NULL men fick NULL – kontrollera generatorn", ("notnull", name))
        finally:
            ctx._resolving.discard(name)
            ctx.column, ctx.state = prev
        ctx.values[name] = value
        return value

    def _history(self) -> dict | None:
        h = self.table.history or {}
        if not h.get("enabled"):
            return None
        f, t = h.get("from"), h.get("to")
        if f not in self.cols or t not in self.cols:
            self.warn("historik (SCD2) är påslagen men giltig från/till-kolumnerna saknas – historiken hoppas över")
            return None
        cur = h.get("current") if h.get("current") in self.cols else None
        changing = [c for c in h.get("changing") or [] if c in self.cols]
        if not changing:
            changing = [c.name for c in self.cols.values() if c.generator.startswith(HISTORY_AUTO) and c.name not in self.fk_cols]
        special = {f, t, cur} | set(changing)
        surrogate = {c for c in self.pk if self.cols[c].generator in ("sequence", "uuid")}
        stable = [c for c in self.out_cols if c not in special and c not in surrogate]
        for u in self.unique_sets:
            if set(u) <= set(stable):
                self.warn(f"historik (SCD2) kräver att {' + '.join(u)} får upprepas, men kolumnerna är unika – historiken hoppas över")
                return None
        open_end = None if (self.cols[t].nullable and h.get("open_end", "NULL") == "NULL") else date(9999, 12, 31)
        return {"from": f, "to": t, "current": cur, "stable": stable, "min": int(h.get("min", 1)), "max": int(h.get("max", 3)), "open": open_end}

    def _make_row(self, ctx: RowContext, rows: list, seen: list, index: int, slot: int, fixed: dict | None = None,
                  fixed_parents: dict | None = None, overrides: dict | None = None):
        """Skapar en rad som uppfyller alla unika villkor, eller None om det inte går."""
        for attempt in range(MAX_ATTEMPTS):
            ctx.reset(index)
            if fixed:
                ctx.values.update(fixed)
                ctx.parents.update(fixed_parents or {})
            for c in self.deferred_cols:
                ctx.values.setdefault(c, None)
            self._fill_fks(ctx, rows, attempt, slot)
            for name in self.out_cols:
                if name not in ctx.values:
                    self.resolve(ctx, name)
            if overrides:
                for name, value in overrides.items():
                    ctx.values[name] = coerce(value, self.cols[name])
            keys = [tuple(ctx.values[c] for c in u) for u in self.unique_sets]
            if not any(None not in k and k in s for k, s in zip(keys, seen)):
                for k, s in zip(keys, seen):
                    if None not in k:
                        s.add(k)
                done: set = set()
                for c, ref in ctx.parents.items():
                    if ref is not None and id(self.seq_counts.get(c)) not in done and c in self.seq_counts:
                        counts = self.seq_counts[c]
                        counts[ref[1]] = counts.get(ref[1], 0) + 1
                        done.add(id(counts))
                return dict(ctx.values), dict(ctx.parents)
        cols = ", ".join(" + ".join(u) for u in self.unique_sets)
        self.warn(f"kunde inte skapa fler unika rader än {len(rows)} (unika kolumner: {cols}). Öka variationen i generatorn eller sänk antalet rader.")
        return None

    def run(self) -> TableData:
        data = TableData(self.table, self.out_cols)
        self._self_data = data
        ctx = RowContext(self)
        seen = [set() for _ in self.unique_sets]
        if self.append:
            known = self.append.existing_keys.get(self.table.key, {})
            for u, s in zip(self.unique_sets, seen):
                s.update(known.get(tuple(u), ()))
        rows = data.rows
        hist = self._history()
        if hist is None:
            for i in range(self.n):
                made = self._make_row(ctx, rows, seen, i, i)
                if made is None:
                    break
                rows.append([made[0][c] for c in self.out_cols])
            return data

        f, t, cur = hist["from"], hist["to"], hist["current"]
        index = 0
        for e in range(self.n):
            versions = self.rng.randint(*sorted((max(1, hist["min"]), max(1, hist["max"]))))
            first = self._make_row(ctx, rows, seen, index, e)
            if first is None:
                break
            values, parents = first
            start = values[f] or self.today - timedelta(days=self.rng.randint(400, 1500))
            start_d = start.date() if isinstance(start, datetime) else start
            bounds = [start_d]
            for _ in range(versions - 1):
                nxt = bounds[-1] + timedelta(days=self.rng.randint(30, 700))
                if nxt > self.today:
                    break
                bounds.append(nxt)
            for v in range(len(bounds)):
                last = v == len(bounds) - 1
                over = {f: bounds[v], t: hist["open"] if last else bounds[v + 1]}
                if cur:
                    over[cur] = last
                if v == 0:
                    for name, value in over.items():
                        values[name] = coerce(value, self.cols[name])
                else:
                    fixed = {c: values[c] for c in hist["stable"]}
                    made = self._make_row(ctx, rows, seen, index, e, fixed, {c: parents.get(c) for c in hist["stable"] if c in parents}, over)
                    if made is None:
                        return data
                    values = {**made[0]}
                rows.append([values[c] for c in self.out_cols])
                index += 1
        return data


# ---------------------------------------------------------------- publik funktion

def ancestors(project: Project, keys: list[str]) -> list[str]:
    out, stack = [], list(keys)
    while stack:
        k = stack.pop()
        t = project.table(k)
        if t is None or t.key in out:
            continue
        out.append(t.key)
        stack += [fk.ref_table for fk in t.foreign_keys]
    return out


def generate(project: Project, only: list[str] | None = None, max_rows: int | None = None,
             progress: Callable[[str, int, int], None] | None = None, scale: float = 1.0,
             append: Append | None = None) -> Result:
    """Genererar data för projektets valda tabeller (eller `only` med sina föräldrar).

    scale  – scenariofaktor som multiplicerar radantalen (inte kodtabeller och kalendrar)
    append – inkrementell körning ovanpå befintlig data, se Append
    """
    from . import library
    library.refresh(project)  # egna generatorer och ändrade listor
    if only:
        keys = [t.key for t in project.tables if t.key in set(ancestors(project, only))]
    else:
        keys = [t.key for t in project.tables if t.include]
    result = Result()
    order, broken = load_order(project, keys)
    broken_ids = {id(fk) for _, fk in broken}
    fake = Faker(project.locale)
    today = date.today()
    for done, key in enumerate(order):
        table = project.table(key)
        if progress:
            progress(key, done, len(order))
        if append is not None and key not in append.new_tables:
            result.data[key] = append.existing.get(key) or TableData(table, [c.name for c in table.columns if not c.computed])
            result.existing.add(key)
            if not result.data[key].rows:
                result.warnings.append(f"{key}: inga befintliga rader hittades i databasen att koppla nya rader till")
            continue
        n = table.rows if table.category in UNSCALED else (max(1, round(table.rows * scale)) if table.rows else 0)
        if append is not None:
            n = max(1, round(n * append.fraction)) if n else 0
        if max_rows is not None:
            n = min(n, max_rows)
        result.data[key] = _TableGen(project, table, max(0, int(n)), result, broken_ids, fake, today, append, max_rows).run()
        result.order.append(key)
    rng = random.Random(f"{project.seed}:deferred")
    for key, fk in broken:
        if key in result.existing:
            continue
        child, parent = result.data[key], result.data.get(fk.ref_table)
        cols = [child.table.column(c) for c in fk.columns]
        if all(c is not None and c.nullable for c in cols):
            result.warnings.append(f"{key}: cirkulär relation till {fk.ref_table} – {', '.join(fk.columns)} sätts till NULL")
            continue
        if parent and parent.rows and all(rc in parent.colidx for rc in fk.ref_columns) and all(c is not None for c in cols):
            for row in child.rows:
                prow = rng.choice(parent.rows)
                for c, rc in zip(cols, fk.ref_columns):
                    row[child.colidx[c.name]] = coerce(prow[parent.colidx[rc]], c)
            result.warnings.append(f"{key}: cirkulär relation till {fk.ref_table} utan NULL-bar kolumn – data är korrekt men kräver att FK-kontrollen stängs av vid laddning till databas")
    if project.dirty.get("tables") and max_rows is None:
        from .dirty import apply_dirty
        apply_dirty(project, result)
    if progress:
        progress("", len(order), len(order))
    return result
