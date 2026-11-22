"""Atomic, explicit-cycle spending limits for optional official OpenAI features.

This dependency-free module is vendored by each application. Applications that
share a filesystem can use the same ledger; otherwise their allocated hard
limits must sum to the organization's available credit. It is an admission
control ledger, not a substitute for the provider's billing statement.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

UTC = timezone.utc

PROJECT_LIMITS = {"vsda": 30_000_000, "deal": 25_000_000, "resume": 15_000_000, "video": 30_000_000}
DEFAULT_TOTAL_LIMIT = 100_000_000


class CreditBudgetError(RuntimeError):
    """An official request cannot safely be admitted or accounted for."""


class BudgetExceeded(CreditBudgetError):
    """The project or organization has insufficient unreserved credit."""


class DuplicateReservation(CreditBudgetError):
    """A request identity was already reserved; do not submit it again."""


@dataclass(frozen=True)
class Reservation:
    """A durable allocation obtained before contacting the provider."""

    id: str
    project: str
    feature: str
    estimated_micros: int
    request_id: str
    state: str = "reserved"


def usd_micros(value: str | int | Decimal) -> int:
    """Parse a nonnegative dollar amount without floating-point rounding."""
    try:
        amount = Decimal(str(value)) * 1_000_000
    except InvalidOperation as exc:
        raise CreditBudgetError("Invalid USD amount") from exc
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise CreditBudgetError("USD amounts must be nonnegative whole microdollars")
    return int(amount)


def _moment(value: str | datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    except ValueError as exc:
        raise CreditBudgetError("Credit cycle dates must be ISO 8601 timestamps") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CreditBudgetError("Credit cycle dates require an explicit timezone")
    return parsed.astimezone(UTC)


def _units(value: int, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > 9_000_000_000_000_000:
        raise CreditBudgetError("Costs must be bounded nonnegative integer microdollars")
    return value


class OpenAICreditMeter:
    """Reserve credit atomically and retain charges of uncertain requests."""

    def __init__(
        self,
        path: str | Path,
        project: str,
        cycle_start: str | datetime,
        cycle_end: str | datetime,
        *,
        total_limit_micros: int = DEFAULT_TOTAL_LIMIT,
        project_limit_micros: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if project not in PROJECT_LIMITS:
            raise CreditBudgetError("Unknown official API budget project")
        self.project = project
        self.start = _moment(cycle_start)
        self.end = _moment(cycle_end)
        if self.end <= self.start:
            raise CreditBudgetError("Credit cycle end must be after its start")
        self.cycle = self.start.isoformat() + "/" + self.end.isoformat()
        self.total_limit = _units(total_limit_micros)
        self.project_limit = _units(PROJECT_LIMITS[project] if project_limit_micros is None else project_limit_micros)
        if self.total_limit > DEFAULT_TOTAL_LIMIT or self.project_limit > PROJECT_LIMITS[project]:
            raise CreditBudgetError("Configured limits cannot exceed the approved allocation")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS credit_cycles (id TEXT PRIMARY KEY, starts TEXT NOT NULL, ends TEXT NOT NULL, total_limit INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS credit_project_limits (cycle TEXT NOT NULL, project TEXT NOT NULL, cap INTEGER NOT NULL, PRIMARY KEY(cycle, project))")
            db.execute("CREATE TABLE IF NOT EXISTS credit_reservations (id TEXT PRIMARY KEY, cycle TEXT NOT NULL, project TEXT NOT NULL, feature TEXT NOT NULL, request_id TEXT NOT NULL, reserved INTEGER NOT NULL, actual INTEGER, state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE(cycle, project, request_id))")
            db.execute("CREATE INDEX IF NOT EXISTS credit_reservations_cycle ON credit_reservations(cycle, project)")
            # Overlapping periods would let a misconfigured process reset spend.
            for row in db.execute("SELECT id, starts, ends FROM credit_cycles WHERE id != ?", (self.cycle,)):
                if _moment(row["starts"]) < self.end and self.start < _moment(row["ends"]):
                    raise CreditBudgetError("Credit cycles in the same ledger must not overlap")
            db.execute("INSERT OR IGNORE INTO credit_cycles VALUES (?, ?, ?, ?)", (self.cycle, self.start.isoformat(), self.end.isoformat(), self.total_limit))
            db.execute("UPDATE credit_cycles SET total_limit = MIN(total_limit, ?) WHERE id = ?", (self.total_limit, self.cycle))
            db.execute("INSERT OR IGNORE INTO credit_project_limits VALUES (?, ?, ?)", (self.cycle, self.project, self.project_limit))
            db.execute("UPDATE credit_project_limits SET cap = MIN(cap, ?) WHERE cycle = ? AND project = ?", (self.project_limit, self.cycle, self.project))

    @classmethod
    def from_env(cls, project: str, environ: Mapping[str, str] | None = None) -> OpenAICreditMeter | None:
        """Build an opt-in meter; enabled but incomplete settings fail closed."""
        env = os.environ if environ is None else environ
        enabled = env.get("OPENAI_OFFICIAL_BUDGET_ENABLED", "false").lower().strip()
        if enabled in {"false", "0", "no", "off", ""}:
            return None
        if enabled not in {"true", "1", "yes", "on"}:
            raise CreditBudgetError("OPENAI_OFFICIAL_BUDGET_ENABLED must be true or false")
        start, end = env.get("OPENAI_CREDIT_CYCLE_START"), env.get("OPENAI_CREDIT_CYCLE_END")
        if not start or not end:
            raise CreditBudgetError("Set OPENAI_CREDIT_CYCLE_START and OPENAI_CREDIT_CYCLE_END to the actual credit period")
        return cls(
            env.get("OPENAI_CREDIT_LEDGER_PATH", ".state/openai-official-credits.sqlite3"),
            project,
            start,
            end,
            total_limit_micros=usd_micros(env.get("OPENAI_CREDIT_TOTAL_USD", "100")),
            project_limit_micros=usd_micros(env["OPENAI_CREDIT_PROJECT_USD"]) if "OPENAI_CREDIT_PROJECT_USD" in env else None,
        )

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _snapshot(self, db: sqlite3.Connection) -> dict[str, Any]:
        rows = list(db.execute("SELECT project, SUM(CASE WHEN state = 'settled' THEN actual ELSE 0 END) AS spent, SUM(CASE WHEN state IN ('reserved', 'submitted', 'unknown') THEN reserved ELSE 0 END) AS held FROM credit_reservations WHERE cycle = ? GROUP BY project", (self.cycle,)))
        spent = sum(row["spent"] or 0 for row in rows)
        held = sum(row["held"] or 0 for row in rows)
        own = next((row for row in rows if row["project"] == self.project), None)
        project_spent, project_held = (int(own["spent"] or 0), int(own["held"] or 0)) if own else (0, 0)
        cap = db.execute("SELECT cap FROM credit_project_limits WHERE cycle = ? AND project = ?", (self.cycle, self.project)).fetchone()[0]
        total = db.execute("SELECT total_limit FROM credit_cycles WHERE id = ?", (self.cycle,)).fetchone()[0]
        used_ratio = max((project_spent + project_held) / cap if cap else 1, (spent + held) / total if total else 1)
        return {
            "project": self.project, "cycle_start": self.start.isoformat(), "cycle_end": self.end.isoformat(),
            "project_limit_micros": cap, "total_limit_micros": total,
            "spent_micros": project_spent, "reserved_micros": project_held,
            "remaining_micros": max(0, min(cap - project_spent - project_held, total - spent - held)),
            "total_spent_micros": spent, "total_reserved_micros": held,
            "total_remaining_micros": max(0, total - spent - held),
            "threshold": "exhausted" if used_ratio >= 1 else "limited" if used_ratio >= 0.95 else "warning" if used_ratio >= 0.8 else "ok",
        }

    def snapshot(self) -> dict[str, Any]:
        """Return current spend, outstanding holds and alert thresholds."""
        with self._transaction() as db:
            return self._snapshot(db)

    def reserve(self, feature: str, estimated_micros: int, request_id: str | None = None, *, nonessential: bool = False) -> Reservation:
        """Allocate a conservative maximum cost before any billable request."""
        _units(estimated_micros, positive=True)
        now = _moment(self.clock())
        if not self.start <= now < self.end:
            raise CreditBudgetError("The configured official API credit period is not active")
        if not feature or len(feature) > 120:
            raise CreditBudgetError("A bounded feature name is required")
        request_id = request_id or uuid4().hex
        if len(request_id) > 240:
            raise CreditBudgetError("Request identity is too long")
        reservation = Reservation(uuid4().hex, self.project, feature, estimated_micros, request_id)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM credit_reservations WHERE cycle = ? AND project = ? AND request_id = ?", (self.cycle, self.project, request_id)).fetchone():
                raise DuplicateReservation("This official request is already recorded; inspect its state before retrying")
            state = self._snapshot(db)
            if estimated_micros > state["remaining_micros"] or (nonessential and state["threshold"] in {"limited", "exhausted"}):
                raise BudgetExceeded("Official API budget is exhausted or reserved by other requests")
            db.execute("INSERT INTO credit_reservations VALUES (?, ?, ?, ?, ?, ?, NULL, 'reserved', ?, ?)", (reservation.id, self.cycle, self.project, feature, request_id, estimated_micros, now.isoformat(), now.isoformat()))
        return reservation

    def _record(self, db: sqlite3.Connection, reservation_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM credit_reservations WHERE id = ? AND cycle = ? AND project = ?", (reservation_id, self.cycle, self.project)).fetchone()
        if row is None:
            raise CreditBudgetError("Unknown reservation for this project and credit cycle")
        return row

    def submitted(self, reservation_id: str) -> None:
        """Mark a possible billable effect immediately before network I/O."""
        with self._transaction() as db:
            row = self._record(db, reservation_id)
            if row["state"] != "reserved":
                raise CreditBudgetError("Only a fresh reservation can be submitted")
            db.execute("UPDATE credit_reservations SET state = 'submitted', updated = ? WHERE id = ?", (self.clock().isoformat(), reservation_id))

    def unknown(self, reservation_id: str) -> None:
        """Retain the full allocation after an uncertain provider outcome."""
        with self._transaction() as db:
            row = self._record(db, reservation_id)
            if row["state"] in {"settled", "released"}:
                return
            db.execute("UPDATE credit_reservations SET state = 'unknown', updated = ? WHERE id = ?", (self.clock().isoformat(), reservation_id))

    def release(self, reservation_id: str) -> None:
        """Release only work known not to have been submitted to the provider."""
        with self._transaction() as db:
            row = self._record(db, reservation_id)
            if row["state"] == "released":
                return
            if row["state"] != "reserved":
                raise CreditBudgetError("Submitted or uncertain requests require cost reconciliation")
            db.execute("UPDATE credit_reservations SET state = 'released', updated = ? WHERE id = ?", (self.clock().isoformat(), reservation_id))

    def settle(self, reservation_id: str, actual_micros: int) -> None:
        """Record known cost exactly once, including an unexpected overrun."""
        _units(actual_micros)
        with self._transaction() as db:
            row = self._record(db, reservation_id)
            if row["state"] == "settled":
                if row["actual"] != actual_micros:
                    raise CreditBudgetError("A settled reservation cannot be repriced implicitly")
                return
            if row["state"] == "released":
                raise CreditBudgetError("A released reservation cannot be settled")
            db.execute("UPDATE credit_reservations SET state = 'settled', actual = ?, updated = ? WHERE id = ?", (actual_micros, self.clock().isoformat(), reservation_id))

    def inspect(self, reservation_id: str) -> dict[str, Any]:
        """Read an allocation for explicit reconciliation or diagnostics."""
        with self._transaction() as db:
            return dict(self._record(db, reservation_id))

    def export_json(self) -> str:
        """Return a credential-free budget summary suitable for telemetry."""
        return json.dumps(self.snapshot(), sort_keys=True)
