from fractions import Fraction

from station.review.evidence import InconsistentEvidenceError
from station.review.lookup import UnknownReportError
from station.setup.shift import ShiftRegistry
from tests.fixtures import StationCase


class TestReview(StationCase):
    def test_reopen_without_probe(self):
        self.open_shift()
        fixed = self.sign('day', (4, 5))
        self.take_source_offline()
        _, lookup = self.reopen()
        result = lookup.read(fixed.report_id)
        self.assertEqual(result.report, fixed)
        self.assertEqual(result.shift.probe.probe_id, 'dust-1')
        self.assertEqual([item.raw_count for item in result.pulses], [4, 5])
        self.assertEqual([item.concentration for item in result.pulses], [Fraction(3), Fraction(7, 2)])
        self.assertEqual([item.exceeded for item in result.pulses], [False, True])
        self.assertEqual(result.recomputed.total, Fraction(13, 2))
        self.assertEqual(result.recomputed.exceeded_pulses, (2,))
        self.assertEqual(result.recomputed.unit, 'μg/m³')

    def test_exact_storage(self):
        expected = Fraction(27670116110564327425, 6)
        count = 2**63 + 1
        self.open_shift(offset='-1/3', limit='27670116110564327425/6')
        fixed = self.sign('day', (count,))
        self.take_source_offline()
        _, lookup = self.reopen()
        result = lookup.read(fixed.report_id)
        self.assertEqual(result.pulses[0].raw_count, count)
        self.assertEqual(result.pulses[0].concentration, expected)
        self.assertFalse(result.pulses[0].exceeded)
        self.assertEqual(fixed.metrics.total, expected)
        self.assertEqual(result.recomputed.total, expected)
        self.assertEqual(result.recomputed.exceeded_pulses, ())

    def test_same_probe_two_shifts(self):
        self.open_shift()
        first = self.sign('day', (4, 5))
        self.open_shift('night', multiplier=1, offset=0, limit=100)
        second = self.sign('night', (4, 5))
        self.take_source_offline()
        _, lookup = self.reopen()
        day = lookup.read(first.report_id)
        night = lookup.read(second.report_id)
        self.assertEqual(day.shift.probe, night.shift.probe)
        self.assertEqual((day.shift.shift_id, night.shift.shift_id), ('day', 'night'))
        self.assertEqual((day.shift.calibration.multiplier, night.shift.calibration.multiplier),
                         (Fraction(1, 2), Fraction(1)))
        self.assertEqual((day.shift.calibration.offset, night.shift.calibration.offset),
                         (Fraction(1), Fraction(0)))
        self.assertEqual((day.shift.threshold.limit, night.shift.threshold.limit),
                         (Fraction(3), Fraction(100)))
        self.assertEqual([pulse.raw_count for pulse in day.pulses], [4, 5])
        self.assertEqual([pulse.raw_count for pulse in night.pulses], [4, 5])
        self.assertEqual((day.recomputed.total, night.recomputed.total), (Fraction(13, 2), Fraction(9)))
        self.assertEqual((day.recomputed.exceeded_pulses, night.recomputed.exceeded_pulses), ((2,), ()))

    def test_inconsistent_row(self):
        self.open_shift()
        fixed = self.sign('day', (4, 5))
        self.take_source_offline()
        store, lookup = self.reopen()
        self.assertEqual(lookup.read(fixed.report_id).recomputed.total, Fraction(13, 2))
        with store.transaction('test-inconsistent-reading') as connection:
            connection.executemany(
                '''UPDATE accepted_readings SET concentration_num = ?, concentration_den = ?
                   WHERE shift_id = 'day' AND pulse = ?''',
                [('0xb', '0x4', '0x1'), ('0xf', '0x4', '0x2')],
            )
        self.assertEqual(Fraction(11, 4) + Fraction(15, 4), fixed.metrics.total)
        self.assertEqual(self.observe('SELECT exceeded FROM accepted_readings ORDER BY receipt_id'),
                         ((0,), (1,)))
        with self.assertRaises(InconsistentEvidenceError):
            lookup.read(fixed.report_id)

    def test_reinitialize(self):
        self.open_shift('custom', 'dust-custom', '2/3', '-1/3', 7)
        report = self.sign('custom', (5, 13))
        self.take_source_offline()
        store, lookup = self.reopen()
        before = lookup.read(report.report_id)
        store.initialize()
        store.initialize()
        shift = ShiftRegistry(store).open('custom', 'dust-custom', '4/6', '-2/6', '14/2')
        self.assertTrue(shift.stopped)
        self.assertEqual(shift.last_pulse, 2)
        self.assertEqual(lookup.read(report.report_id), before)
        self.assertEqual(before.recomputed.total, Fraction(34, 3))
        self.assertEqual(before.recomputed.exceeded_pulses, (2,))
        self.assertEqual([item.raw_count for item in before.pulses], [5, 13])

    def test_unknown_receipt(self):
        self.open_shift()
        fixed = self.sign('day', (4,))
        self.take_source_offline()
        _, lookup = self.reopen()
        with self.assertRaises(UnknownReportError):
            lookup.read(fixed.report_id + 1)
