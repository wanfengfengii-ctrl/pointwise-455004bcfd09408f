from station.acquisition.clock import InvalidPulseTokenError, PulseInProgressError
from station.acquisition.queue import QueueFullError
from tests.fixtures import StationCase


class TestAcquisition(StationCase):
    capacity = 1

    def test_full_queue_pauses(self):
        session = self.open_shift()
        first = self.complete(session, 4)
        self.assertEqual(first.pulse, 1)
        with self.assertRaises(QueueFullError):
            session.start()
        self.assertEqual(session.pending_reading(1), first)
        accepted = self.dispatch.deliver(session, 1)
        self.assertEqual(accepted.raw, first)
        self.assertIsNone(session.pending_reading(1))
        self.assertEqual(session.start().pulse, 2)

    def test_mismatched_ack(self):
        day = self.open_shift()
        night = self.open_shift('night')
        first = self.complete(day, 4)
        other = self.complete(night, 4)
        other_receipt = self.dispatch.deliver(night, other.pulse).receipt
        self.assertFalse(day.confirm(other_receipt))
        self.assertEqual(day.pending_reading(1), first)
        with self.assertRaises(QueueFullError):
            day.start()
        receipt = self.dispatch.deliver(day, 1).receipt
        second = self.complete(day, 5)
        self.assertEqual(second.pulse, 2)
        self.assertFalse(day.confirm(receipt))
        self.assertEqual(day.pending_reading(2), second)

    def test_wrong_completion_token(self):
        day = self.open_shift()
        night = self.open_shift('night')
        day_token = day.start()
        night_token = night.start()
        self.assertEqual(day_token.pulse, night_token.pulse)
        with self.assertRaises(InvalidPulseTokenError):
            day.finish(night_token, 99)
        self.assertIsNone(day.pending_reading(1))
        correct = day.finish(day_token, 4)
        self.assertEqual((correct.shift_id, correct.probe_id, correct.pulse, correct.raw_count),
                         ('day', 'dust-1', 1, 4))
        self.assertEqual(night.finish(night_token, 8).raw_count, 8)

    def test_invalid_count(self):
        session = self.open_shift()
        token = session.start()
        for bad in (None, -1, True, 4.0, '4'):
            with self.subTest(count=bad):
                with self.assertRaises(ValueError):
                    session.finish(token, bad)
                self.assertIsNone(session.pending_reading(1))
        with self.assertRaises(PulseInProgressError):
            session.start()
        self.assertEqual(session.finish(token, 0).raw_count, 0)

    def test_stale_token(self):
        session = self.open_shift()
        old = session.start()
        session.finish(old, 4)
        self.dispatch.deliver(session, 1)
        current = session.start()
        with self.assertRaises(InvalidPulseTokenError):
            session.finish(old, 99)
        self.assertIsNone(session.pending_reading(2))
        saved = session.finish(current, 5)
        self.assertEqual((saved.pulse, saved.raw_count), (2, 5))
