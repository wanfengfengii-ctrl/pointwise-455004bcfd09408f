from dataclasses import replace
from fractions import Fraction

from station.acquisition.queue import QueueFullError
from station.intake.admit import AdmissionConflictError
from station.intake.records import AcceptedRecords
from station.setup.shift import ShiftConflictError, ShiftRegistry, UnknownShiftError
from tests.fixtures import CommitRejected, StationCase


class TestIntake(StationCase):
    capacity = 1

    def test_exact_threshold(self):
        session = self.open_shift()
        self.complete(session, 4)
        first = self.dispatch.deliver(session, 1)
        self.complete(session, 5)
        second = self.dispatch.deliver(session, 2)
        self.assertEqual((first.concentration, second.concentration), (Fraction(3), Fraction(7, 2)))
        self.assertEqual((first.exceeded, second.exceeded), (False, True))
        with self.store.snapshot() as connection:
            durable = AcceptedRecords.for_shift(connection, 'day')
        self.assertEqual(durable, (first, second))
        session.stop()
        report = self.issuer.issue('day')
        self.assertEqual(report.metrics.total, Fraction(13, 2))
        self.assertEqual(report.metrics.exceeded_pulses, (2,))

    def test_frozen_policy(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        same = self.bridge.open('day', 'dust-1', '2/4', '3/3', '9/3')
        self.assertEqual(same.calibration.multiplier, Fraction(1, 2))
        self.assertIs(self.bridge.session('day'), session)
        self.assertEqual(session.pending_reading(1), raw)
        with self.assertRaises(ShiftConflictError):
            self.bridge.open('day', 'dust-1', '1/2', 1, 4)
        for bad_multiplier in (0, '-1/2', '1/0', True, 0.5):
            with self.subTest(multiplier=bad_multiplier):
                with self.assertRaises(ValueError):
                    self.bridge.open('invalid', 'dust-1', bad_multiplier, 1, 3)
        with self.assertRaises(UnknownShiftError):
            ShiftRegistry(self.store).get('invalid')
        with self.assertRaises(ValueError):
            self.bridge.open('bad-probe', '  ', 1, 0, 3)
        accepted = self.dispatch.deliver(session, 1)
        self.assertEqual((accepted.concentration, accepted.exceeded), (Fraction(3), False))
        token = session.start()
        self.bridge.open('day', 'dust-1', '0.5', 1, 3)
        self.assertEqual(session.finish(token, 5).pulse, 2)

    def test_failed_commit_preserves_slot(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        boundary = self.gate.arm('admit', fail=True)
        with self.assertRaises(CommitRejected):
            self.dispatch.deliver(session, 1)
        self.assertTrue(boundary.reached.is_set())
        self.assertEqual(self.observe('SELECT receipt_id FROM accepted_readings'), ())
        self.assertEqual(session.pending_reading(1), raw)
        with self.assertRaises(QueueFullError):
            session.start()
        accepted = self.dispatch.deliver(session, 1)
        self.assertEqual(self.admission.admit(raw), accepted)
        self.assertIsNone(session.pending_reading(1))
        self.assertEqual(self.observe('SELECT receipt_id FROM accepted_readings'),
                         ((accepted.receipt.receipt_id,),))
        self.assertEqual(session.start().pulse, 2)

    def test_lost_ack(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        accepted = self.admission.admit(raw)
        self.assertEqual(session.pending_reading(1), raw)
        with self.assertRaises(QueueFullError):
            session.start()
        recovered = self.dispatch.deliver(session, 1)
        self.assertEqual(recovered, accepted)
        self.assertIsNone(session.pending_reading(1))
        self.assertEqual(self.observe('SELECT receipt_id FROM accepted_readings'),
                         ((accepted.receipt.receipt_id,),))
        self.assertEqual(session.start().pulse, 2)

    def test_conflicting_replay(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        original = self.admission.admit(raw)
        with self.assertRaises(AdmissionConflictError):
            self.admission.admit(replace(raw, raw_count=5))
        with self.assertRaises(AdmissionConflictError):
            self.admission.admit(replace(raw, probe_id='unbound-probe'))
        self.assertEqual(session.pending_reading(1), raw)
        self.assertEqual(self.dispatch.deliver(session, 1), original)
        self.assertEqual(self.observe('SELECT receipt_id FROM accepted_readings'),
                         ((original.receipt.receipt_id,),))
