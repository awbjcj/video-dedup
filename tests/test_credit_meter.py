"""Real SQLite admission tests; no provider requests or credentials."""

import concurrent.futures
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from openai_credit_meter import (
    BudgetExceeded, CreditBudgetError, DuplicateReservation,
    OpenAICreditMeter, PROJECT_LIMITS, usd_micros,
)


class CreditMeterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "credits.sqlite3"
        self.start, self.end = "2026-11-10T00:00:00Z", "2026-12-10T00:00:00Z"
        self.now = datetime(2026, 11, 21, tzinfo=timezone.utc)

    def meter(self, project="video", **kwargs):
        return OpenAICreditMeter(self.path, project, self.start, self.end,
                                clock=lambda: self.now, **kwargs)

    def test_approved_allocations_total_one_hundred(self):
        self.assertEqual(sum(PROJECT_LIMITS.values()), 100_000_000)
        self.assertEqual(PROJECT_LIMITS["video"], 30_000_000)
        with self.assertRaises(CreditBudgetError):
            self.meter(project_limit_micros=30_000_001)

    def test_concurrent_reservations_cannot_overspend(self):
        meter = self.meter(project_limit_micros=100)
        def reserve(number):
            try:
                return meter.reserve("concurrent", 10, str(number)).id
            except BudgetExceeded:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(reserve, range(50)))
        self.assertEqual(sum(value is not None for value in results), 10)
        self.assertEqual(meter.snapshot()["reserved_micros"], 100)

    def test_cross_project_global_cap(self):
        video = self.meter(total_limit_micros=100)
        deal = self.meter("deal")
        video.reserve("video", 60)
        with self.assertRaises(BudgetExceeded):
            deal.reserve("deal", 41)
        deal.reserve("deal", 40)
        self.assertEqual(video.snapshot()["total_remaining_micros"], 0)

    def test_unknown_is_durable_and_cannot_be_released(self):
        meter = self.meter()
        reservation = meter.reserve("audio", 100, "audio-hash")
        meter.submitted(reservation.id)
        meter.unknown(reservation.id)
        reopened = self.meter()
        self.assertEqual(reopened.snapshot()["reserved_micros"], 100)
        with self.assertRaises(CreditBudgetError):
            reopened.release(reservation.id)
        with self.assertRaises(DuplicateReservation):
            reopened.reserve("audio", 100, "audio-hash")
        with self.assertRaises(CreditBudgetError):
            reopened.allow_retry_after_settlement(reservation.id)
        reopened.settle(reservation.id, 90)
        reopened.settle(reservation.id, 90)
        self.assertEqual(reopened.snapshot()["spent_micros"], 90)
        self.assertEqual(reopened.snapshot()["reserved_micros"], 0)
        with self.assertRaises(CreditBudgetError):
            reopened.settle(reservation.id, 91)

    def test_release_only_before_submission(self):
        meter = self.meter()
        reservation = meter.reserve("before-send", 10)
        meter.release(reservation.id)
        meter.release(reservation.id)
        self.assertEqual(meter.snapshot()["reserved_micros"], 0)
        with self.assertRaises(CreditBudgetError):
            meter.submitted(reservation.id)

    def test_released_request_can_be_retried_once_without_losing_history(self):
        meter = self.meter()
        released = meter.reserve("audio", 10, "audio-hash")
        meter.release(released.id)

        def retry(_):
            try:
                return meter.reserve("audio", 10, "audio-hash")
            except DuplicateReservation:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(retry, range(4)))
        admitted = [result for result in results if result is not None]
        self.assertEqual(len(admitted), 1)
        self.assertNotEqual(admitted[0].id, released.id)
        self.assertEqual(meter.inspect(released.id)["state"], "released")
        meter.release(released.id)  # A stale caller cannot release the new hold.
        self.assertEqual(meter.inspect(admitted[0].id)["state"], "reserved")
        self.assertEqual(meter.snapshot()["reserved_micros"], 10)

    def test_thresholds_and_truthful_overrun(self):
        meter = self.meter(project_limit_micros=100)
        r = meter.reserve("essential", 80)
        self.assertEqual(meter.snapshot()["threshold"], "warning")
        meter.settle(r.id, 95)
        self.assertEqual(meter.snapshot()["threshold"], "limited")
        with self.assertRaises(BudgetExceeded):
            meter.reserve("optional", 1, nonessential=True)
        r = meter.reserve("essential", 5)
        meter.settle(r.id, 10)
        self.assertEqual(meter.snapshot()["spent_micros"], 105)
        self.assertEqual(meter.snapshot()["remaining_micros"], 0)

    def test_periods_are_explicit_nonoverlapping_and_expire(self):
        self.meter()
        with self.assertRaises(CreditBudgetError):
            OpenAICreditMeter(self.path, "video", "2026-11-01T00:00:00Z", self.end)
        self.now = datetime(2026, 12, 10, tzinfo=timezone.utc)
        with self.assertRaises(CreditBudgetError):
            self.meter().reserve("expired", 1)
        next_period = OpenAICreditMeter(self.path, "video", self.end, "2027-01-10T00:00:00Z",
                                      clock=lambda: self.now)
        self.assertEqual(next_period.snapshot()["spent_micros"], 0)
        next_period.reserve("new-cycle", 1)

    def test_submission_is_rejected_at_cycle_end(self):
        meter = self.meter()
        reservation = meter.reserve("audio", 100)
        self.now = datetime(2026, 12, 10, tzinfo=timezone.utc)
        with self.assertRaises(CreditBudgetError):
            meter.submitted(reservation.id)
        meter.release(reservation.id)
        self.assertEqual(meter.snapshot()["reserved_micros"], 0)

    def test_reservation_rechecks_cycle_after_acquiring_ledger_lock(self):
        meter = self.meter()
        transaction = meter._transaction

        @contextmanager
        def transaction_at_cycle_end():
            with transaction() as db:
                self.now = datetime(2026, 12, 10, tzinfo=timezone.utc)
                yield db

        with mock.patch.object(meter, "_transaction", transaction_at_cycle_end):
            with self.assertRaises(CreditBudgetError):
                meter.reserve("audio", 100)
        self.assertEqual(meter.snapshot()["reserved_micros"], 0)

    def test_configuration_fails_closed(self):
        self.assertIsNone(OpenAICreditMeter.from_env("video", {}))
        with self.assertRaises(CreditBudgetError):
            OpenAICreditMeter.from_env("video", {"OPENAI_OFFICIAL_BUDGET_ENABLED": "true"})
        for invalid in ("NaN", "Infinity", "-1", "0.0000001", "garbage"):
            with self.subTest(invalid=invalid), self.assertRaises(CreditBudgetError):
                usd_micros(invalid)
        self.assertEqual(usd_micros("0.0045"), 4500)
        meter = self.meter()
        for invalid in (False, 0, -1, 1.5, 9_000_000_000_000_001):
            with self.subTest(invalid=invalid), self.assertRaises(CreditBudgetError):
                meter.reserve("invalid", invalid)

    def test_existing_caps_cannot_be_raised_by_restart(self):
        self.meter(project_limit_micros=100)
        self.assertEqual(self.meter().snapshot()["project_limit_micros"], 100)


if __name__ == "__main__":
    unittest.main()
