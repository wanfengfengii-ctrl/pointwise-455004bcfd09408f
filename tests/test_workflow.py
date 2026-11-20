from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from station.acquisition.clock import AcquisitionStateError
from station.acquisition.queue import QueueFullError
from station.report.issue import ShiftNotStoppedError
from station.setup.shift import ShiftRegistry
from tests.fixtures import CommitRejected, StationCase


class TestWorkflow(StationCase):
    def test_staged_admission_preserves_capacity_until_commit(self):
        session = self.open_shift()
        first = self.complete(session, 4)
        token = session.start()
        boundary = self.gate.arm('admit', pause=True)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.dispatch.deliver, session, 1)
            try:
                boundary.wait()
                second = session.finish(token, 5)
                self.assertEqual(session.pending_reading(1), first)
                self.assertEqual(session.pending_reading(2), second)
                self.assertEqual(self.observe('SELECT receipt_id FROM accepted_readings'), ())
                with self.assertRaises(QueueFullError):
                    session.start()
            finally:
                boundary.resume.set()
            accepted = future.result(timeout=10)
        self.assertEqual(accepted.raw, first)
        self.assertIsNone(session.pending_reading(1))
        self.assertEqual(session.pending_reading(2), second)
        self.assertEqual(session.start().pulse, 3)

    def test_failed_stop_keeps_shift_open(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        boundary = self.gate.arm('stop', pause=True, fail=True)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(session.stop)
            try:
                boundary.wait()
                self.assertEqual(self.observe('SELECT stopped FROM shifts'), ((0,),))
                self.assertEqual(self.observe('SELECT last_pulse FROM shift_stops'), ())
                self.assertEqual(session.pending_reading(1), raw)
                with self.assertRaises(AcquisitionStateError):
                    session.start()
            finally:
                boundary.resume.set()
            with self.assertRaises(CommitRejected):
                future.result(timeout=10)
        self.assertFalse(ShiftRegistry(self.store).get('day').stopped)
        with self.assertRaises(ShiftNotStoppedError):
            self.issuer.issue('day')
        second = self.complete(session, 5)
        self.assertEqual(second.pulse, 2)
        self.assertEqual(session.stop().last_pulse, 2)
        for pulse in (1, 2):
            self.dispatch.deliver(session, pulse)
        self.assertEqual(self.issuer.issue('day').metrics.total, Fraction(13, 2))

    def test_archive_uses_numeric_pulse_order(self):
        session = self.open_shift(multiplier=1, offset=0, limit=14)
        for count in range(1, 18):
            raw = self.complete(session, count)
            self.dispatch.deliver(session, raw.pulse)
        session.stop()
        report = self.issuer.issue('day')
        self.take_source_offline()
        _, lookup = self.reopen()
        view = lookup.read(report.report_id)
        self.assertEqual(tuple(item.pulse for item in view.pulses), tuple(range(1, 18)))
        self.assertEqual(view.recomputed.total, Fraction(153))
        self.assertEqual(view.recomputed.exceeded_pulses, (15, 16, 17))
