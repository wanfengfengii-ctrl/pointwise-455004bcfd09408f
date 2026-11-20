from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from station.acquisition.clock import (
    AcquisitionStateError,
    CaptureStoppedError,
    PulseInProgressError,
)
from station.acquisition.session import AcquisitionBridge
from station.intake.admit import AdmissionService, UnknownBatchError
from station.intake.store import StationStore
from station.setup.shift import ShiftConflictError, UnknownShiftError
from tests.cases import expected_rows, load_cases
from tests.fixtures import CommitRejected, StationCase


class TestOverrunShift(StationCase):
    capacity = 2

    def open_overrun(self, shift_id='day'):
        self.bridge.open(shift_id, 'dust-1', '1/2', 1, 3, overrun=True)
        return self.bridge.session(shift_id)

    @staticmethod
    def pulse(session, count):
        return session.finish(session.start(), count)

    def test_slots_overflow_into_missing(self):
        session = self.open_overrun()
        self.assertEqual(self.pulse(session, 4).pulse, 1)
        self.assertEqual(self.pulse(session, 5).pulse, 2)
        self.assertIsNone(self.pulse(session, 6))
        self.assertIsNone(self.pulse(session, 7))
        self.assertEqual(session.completed_through(), 4)
        token = session.start()
        self.assertEqual(token.pulse, 5)
        with self.assertRaises(PulseInProgressError):
            session.start()
        self.assertIsNone(session.finish(token, 8))
        self.assertEqual([reading.pulse for reading in session.held_readings()], [1, 2])
        batch = self.dispatch.deliver_prefix(session)
        self.assertEqual([row['pulse'] for row in batch['rows']], [1, 2, 3, 4, 5])
        self.assertEqual(session.finish(session.start(), 8).pulse, 6)

    def test_first_batch_keeps_tail_gaps(self):
        session = self.open_overrun()
        for count in (4, 5, 6, 7):
            self.pulse(session, count)
        batch = self.dispatch.deliver_prefix(session)
        self.assertEqual(batch['shift_id'], 'day')
        self.assertEqual(batch['probe_id'], 'dust-1')
        self.assertEqual((batch['first_pulse'], batch['last_pulse']), (1, 4))
        self.assertEqual(batch['rows'], [
            {'pulse': 1, 'raw_count': 4, 'concentration': Fraction(3), 'exceeded': False},
            {'pulse': 2, 'raw_count': 5, 'concentration': Fraction(7, 2), 'exceeded': True},
            {'pulse': 3, 'missing': 'overrun'},
            {'pulse': 4, 'missing': 'overrun'},
        ])
        self.assertIsNone(session.pending_reading(1))
        self.assertIsNone(session.pending_reading(2))
        self.assertIsNone(self.dispatch.deliver_prefix(session))
        self.assertEqual(self.observe('SELECT COUNT(*) FROM delivery_batches'), ((1,),))

    def test_in_flight_pulse_waits_for_next_batch(self):
        session = self.open_overrun()
        for count in (4, 5):
            self.pulse(session, count)
        token = session.start()
        batch = self.dispatch.deliver_prefix(session)
        self.assertEqual(batch['last_pulse'], 2)
        self.assertEqual([row['pulse'] for row in batch['rows']], [1, 2])
        self.assertIsNone(self.dispatch.deliver_prefix(session))
        reading = session.finish(token, 7)
        self.assertEqual(reading.pulse, 3)
        follow_up = self.dispatch.deliver_prefix(session)
        self.assertEqual(follow_up['first_pulse'], 3)
        self.assertEqual(follow_up['rows'], [
            {'pulse': 3, 'raw_count': 7, 'concentration': Fraction(9, 2), 'exceeded': True},
        ])

    def test_failed_batch_keeps_readings_and_position(self):
        session = self.open_overrun()
        for count in (4, 5, 6, 7):
            self.pulse(session, count)
        token = session.start()
        boundary = self.gate.arm('deliver_prefix', fail=True)
        with self.assertRaises(CommitRejected):
            self.dispatch.deliver_prefix(session)
        self.assertTrue(boundary.reached.is_set())
        self.assertEqual(self.observe('SELECT batch_id FROM delivery_batches'), ())
        self.assertEqual(self.observe('SELECT shift_id FROM delivery_cursors'), ())
        self.assertEqual([reading.pulse for reading in session.held_readings()], [1, 2])
        self.assertIsNone(session.finish(token, 8))
        retry = self.dispatch.deliver_prefix(session)
        self.assertEqual(retry['rows'], [
            {'pulse': 1, 'raw_count': 4, 'concentration': Fraction(3), 'exceeded': False},
            {'pulse': 2, 'raw_count': 5, 'concentration': Fraction(7, 2), 'exceeded': True},
            {'pulse': 3, 'missing': 'overrun'},
            {'pulse': 4, 'missing': 'overrun'},
            {'pulse': 5, 'missing': 'overrun'},
        ])
        self.assertEqual(session.held_readings(), ())

    def test_reading_retained_while_commit_is_paused(self):
        session = self.open_overrun()
        self.pulse(session, 4)
        token = session.start()
        boundary = self.gate.arm('deliver_prefix', pause=True)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.dispatch.deliver_prefix, session)
            try:
                boundary.wait()
                self.assertIsNotNone(session.finish(token, 5))
                self.assertEqual(self.observe('SELECT batch_id FROM delivery_batches'), ())
            finally:
                boundary.resume.set()
            first = future.result(timeout=10)
        self.assertEqual(first['rows'], [
            {'pulse': 1, 'raw_count': 4, 'concentration': Fraction(3), 'exceeded': False},
        ])
        second_batch = self.dispatch.deliver_prefix(session)
        self.assertEqual(second_batch['rows'], [
            {'pulse': 2, 'raw_count': 5, 'concentration': Fraction(7, 2), 'exceeded': True},
        ])

    def test_prefix_survives_source_reopen(self):
        session = self.open_overrun()
        for count in (4, 5, 6, 7):
            self.pulse(session, count)
        first = self.dispatch.deliver_prefix(session)
        session.finish(session.start(), 9)
        second = self.dispatch.deliver_prefix(session)
        self.assertEqual(second['rows'], [
            {'pulse': 5, 'raw_count': 9, 'concentration': Fraction(11, 2), 'exceeded': True},
        ])
        self.take_source_offline()
        store, _ = self.reopen()
        admission = AdmissionService(store)
        self.assertEqual(admission.read_prefix('day'), first['rows'] + second['rows'])
        self.assertEqual(admission.read_batch(first['batch_id']), first)
        self.assertEqual(admission.read_batch(second['batch_id']), second)
        with self.assertRaises(UnknownShiftError):
            admission.read_prefix('absent')
        with self.assertRaises(UnknownBatchError):
            admission.read_batch(second['batch_id'] + 100)

    def test_unregistered_shift_has_empty_prefix(self):
        self.bridge.open('quiet', 'dust-1', 1, 0, 3)
        self.assertEqual(AdmissionService(self.store).read_prefix('quiet'), [])

    def test_mode_and_capacity_are_frozen(self):
        session = self.open_overrun()
        same = self.bridge.open('day', 'dust-1', '2/4', '3/3', '9/3', overrun=True)
        self.assertFalse(same.stopped)
        self.assertIs(self.bridge.session('day'), session)
        with self.assertRaises(ShiftConflictError):
            self.bridge.open('day', 'dust-1', '1/2', 1, 3)
        same_again = self.bridge.open('day', 'dust-1', '1/2', 1, 3, overrun=True)
        self.assertEqual(same_again.calibration.multiplier, Fraction(1, 2))
        self.assertIs(self.bridge.session('day'), session)

        store = StationStore(self.db_path)
        self.addCleanup(store.close)
        store.initialize()
        with self.assertRaises(ShiftConflictError):
            AcquisitionBridge(store, 1).open('day', 'dust-1', '1/2', 1, 3, overrun=True)

    def test_ordinary_shift_keeps_individual_delivery(self):
        session = self.open_shift()
        raw = self.complete(session, 4)
        with self.assertRaises(AcquisitionStateError):
            self.dispatch.deliver_prefix(session)
        accepted = self.dispatch.deliver(session, 1)
        self.assertEqual(accepted.raw, raw)
        self.assertFalse(session.confirm(accepted.receipt))

    def test_overrun_shift_refuses_single_delivery(self):
        session = self.open_overrun()
        self.pulse(session, 4)
        with self.assertRaises(AcquisitionStateError):
            self.dispatch.deliver(session, 1)
        self.assertEqual([reading.pulse for reading in session.held_readings()], [1])

    def test_invalid_counts_keep_active_token(self):
        session = self.open_overrun()
        token = session.start()
        for bad in (None, -1, True, 4.0, '4'):
            with self.subTest(count=bad):
                with self.assertRaises(ValueError):
                    session.finish(token, bad)
        self.assertIsNone(session.pending_reading(1))
        with self.assertRaises(PulseInProgressError):
            session.start()
        self.assertEqual(session.finish(token, 1).pulse, 1)

    def test_stop_still_seals_overrun_shift(self):
        session = self.open_overrun()
        self.pulse(session, 4)
        self.assertEqual(session.stop().last_pulse, 1)
        with self.assertRaises(CaptureStoppedError):
            session.start()
        batch = self.dispatch.deliver_prefix(session)
        self.assertEqual(batch['last_pulse'], 1)

    def test_repeat_delivery_never_overwrites_old_rows(self):
        session = self.open_overrun()
        for count in (4, 5, 6, 7):
            self.pulse(session, count)
        first = self.dispatch.deliver_prefix(session)
        rows_before = self.observe('SELECT batch_id, pulse, raw_count, missing FROM delivery_rows')
        self.pulse(session, 8)
        second = self.dispatch.deliver_prefix(session)
        self.assertNotEqual(first['batch_id'], second['batch_id'])
        self.assertEqual(self.observe(
            'SELECT batch_id, pulse, raw_count, missing FROM delivery_rows '
            'WHERE batch_id = ?', (first['batch_id'],)),
            tuple(row for row in rows_before if row[0] == first['batch_id']))
        self.assertEqual(AdmissionService(self.store).read_batch(first['batch_id']), first)
        self.assertEqual(AdmissionService(self.store).read_batch(second['batch_id']), second)
        with self.store.transaction('test-tamper') as connection:
            connection.execute(
                'UPDATE delivery_rows SET raw_count = ? WHERE batch_id = ? AND pulse = ?',
                ('0x63', first['batch_id'], '0x1'),
            )
        with self.assertRaises(ValueError):
            AdmissionService(self.store).read_batch(first['batch_id'])

    def test_slot_released_even_if_release_was_skipped(self):
        session = self.open_overrun()
        for count in (4, 5):
            self.pulse(session, count)
        with self.store.transaction('deliver_prefix') as connection:
            from station.intake.delivery import DeliveryLedger, DeliveredReading, OverrunRow
            DeliveryLedger.publish(
                connection, 'day', 'dust-1', 1, 2,
                [DeliveredReading(1, 4, Fraction(3), False),
                 DeliveredReading(2, 5, Fraction(7, 2), True)],
            )
        self.assertEqual(len(session.held_readings()), 2)
        self.assertIsNone(self.dispatch.deliver_prefix(session))
        self.assertEqual(session.held_readings(), ())


class TestOverloadCases(StationCase):
    """Drive the packaged event scripts end to end on fresh shifts."""

    capacity = 2

    def setUp(self):
        super().setUp()
        self.cases = load_cases()
        shift = self.cases['shift']
        self.capacity = shift['capacity']
        self.bridge = AcquisitionBridge(self.store, self.capacity)

    def open_case_shift(self, shift_id):
        shift = self.cases['shift']
        self.bridge.open(
            shift_id,
            shift['probe_id'],
            shift['multiplier'],
            shift['offset'],
            shift['limit'],
            overrun=True,
        )
        return self.bridge.session(shift_id)

    def test_tail_overrun(self):
        case = self.cases['tail_overrun']
        shift = self.cases['shift']
        session = self.open_case_shift(shift['shift_id'])
        for count in case['completed_counts']:
            session.finish(session.start(), count)
        in_flight = session.start()  # pulse 5 stays in flight across the first delivery

        first = self.dispatch.deliver_prefix(session)
        self.assertEqual(first['rows'], expected_rows(case['first_rows']))
        self.assertEqual((first['first_pulse'], first['last_pulse']), (1, 4))
        self.assertIsNone(self.dispatch.deliver_prefix(session))
        self.assertEqual(in_flight.pulse, 5)

        failed_session = self.open_case_shift('tail-retry')
        for count in case['completed_counts']:
            failed_session.finish(failed_session.start(), count)
        pending_token = failed_session.start()
        before = self.observe('SELECT COUNT(*) FROM delivery_batches')
        self.gate.arm('deliver_prefix', fail=True)
        with self.assertRaises(CommitRejected):
            self.dispatch.deliver_prefix(failed_session)
        self.assertEqual(self.observe('SELECT COUNT(*) FROM delivery_batches'), before)
        self.assertEqual(self.observe(
            'SELECT COUNT(*) FROM delivery_cursors WHERE shift_id = ?', ('tail-retry',)), ((0,),))
        self.assertEqual(len(failed_session.held_readings()), 2)
        failed_session.finish(pending_token, case['active_count'])
        retry = self.dispatch.deliver_prefix(failed_session)
        self.assertEqual(retry['rows'], expected_rows(case['retry_rows']))
        self.assertEqual(failed_session.held_readings(), ())

        failed_session.finish(failed_session.start(), case['next_count'])
        next_batch = self.dispatch.deliver_prefix(failed_session)
        self.assertEqual(next_batch['rows'], expected_rows(case['next_rows']))

        self.take_source_offline()
        store, _ = self.reopen()
        admission = AdmissionService(store)
        self.assertEqual(admission.read_prefix('tail-retry'),
                         expected_rows(case['retry_rows'] + case['next_rows']))
        self.assertEqual(admission.read_batch(retry['batch_id']), retry)
        self.assertEqual(admission.read_batch(next_batch['batch_id']), next_batch)

    def test_retained_during_commit(self):
        case = self.cases['retained_during_commit']
        shift = self.cases['shift']
        session = self.open_case_shift('retained')
        for count in case['completed_counts']:
            session.finish(session.start(), count)
        active = session.start()

        boundary = self.gate.arm('deliver_prefix', pause=True)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.dispatch.deliver_prefix, session)
            try:
                boundary.wait()
                self.assertIsNotNone(session.finish(active, case['active_count']))
            finally:
                boundary.resume.set()
            first = future.result(timeout=10)
        self.assertEqual(first['rows'], expected_rows(case['first_rows']))
        second = self.dispatch.deliver_prefix(session)
        self.assertEqual(second['rows'], expected_rows(case['next_rows']))
