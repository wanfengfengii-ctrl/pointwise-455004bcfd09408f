from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction

from station.acquisition.clock import CaptureStoppedError, PulseInProgressError
from station.intake.admit import AdmissionConflictError
from station.report.archive import ReportArchive
from station.report.coverage import IncompleteCoverageError
from station.report.issue import ShiftNotStoppedError
from station.review.lookup import ReportLookup
from tests.fixtures import CommitRejected, StationCase


class TestReport(StationCase):
    def test_stop_before_last_admission(self):
        session = self.open_shift()
        self.complete(session, 4)
        self.dispatch.deliver(session, 1)
        last = self.complete(session, 5)
        self.assertEqual(session.stop().last_pulse, 2)
        with self.assertRaises(IncompleteCoverageError):
            self.issuer.issue('day')
        self.assertEqual(self.observe('SELECT report_id FROM reports'), ())
        self.assertEqual(session.pending_reading(2), last)
        with self.assertRaises(AdmissionConflictError):
            self.admission.admit(replace(last, pulse=3))
        self.dispatch.deliver(session, 2)
        report = self.issuer.issue('day')
        view = ReportLookup(self.store).read(report.report_id)
        self.assertEqual([pulse.pulse for pulse in view.pulses], [1, 2])
        self.assertEqual(report.metrics.total, Fraction(13, 2))
        self.assertEqual(report.metrics.exceeded_pulses, (2,))

    def test_stop_state(self):
        session = self.open_shift()
        with self.assertRaises(ShiftNotStoppedError):
            self.issuer.issue('day')
        token = session.start()
        with self.assertRaises(PulseInProgressError):
            session.stop()
        self.assertEqual(self.observe('SELECT shift_id FROM shift_stops'), ())
        raw = session.finish(token, 4)
        self.assertEqual(session.stop().last_pulse, 1)
        with self.assertRaises(CaptureStoppedError):
            session.start()
        with self.assertRaises(CaptureStoppedError):
            session.stop()
        self.assertEqual(self.dispatch.deliver(session, 1).raw, raw)
        self.assertEqual(self.issuer.issue('day').last_pulse, 1)

    def test_ordered_members(self):
        session = self.open_shift()
        self.complete(session, 4)
        self.complete(session, 5)
        second = self.dispatch.deliver(session, 2)
        first = self.dispatch.deliver(session, 1)
        self.assertLess(second.receipt.receipt_id, first.receipt.receipt_id)
        session.stop()
        report = self.issuer.issue('day')
        with self.store.snapshot() as connection:
            keys = ReportArchive.member_keys(connection, report.report_id)
        self.assertEqual([(key.ordinal, key.source_shift_id, key.source_pulse) for key in keys],
                         [(1, 'day', 1), (2, 'day', 2)])
        view = ReportLookup(self.store).read(report.report_id)
        self.assertEqual([pulse.raw_count for pulse in view.pulses], [4, 5])
        self.assertEqual(report.metrics.exceeded_pulses, (2,))

    def test_issue_rollback(self):
        session = self.open_shift()
        for count in (4, 5):
            raw = self.complete(session, count)
            self.dispatch.deliver(session, raw.pulse)
        session.stop()
        boundary = self.gate.arm('issue', pause=True, fail=True)
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(self.issuer.issue, 'day')
            try:
                boundary.wait()
                self.assertEqual(self.observe('SELECT report_id FROM reports'), ())
                self.assertEqual(self.observe('SELECT ordinal FROM report_members'), ())
            finally:
                boundary.resume.set()
            with self.assertRaises(CommitRejected):
                future.result(timeout=10)
        self.assertEqual(self.observe('SELECT report_id FROM reports'), ())
        self.assertEqual(self.observe('SELECT ordinal FROM report_members'), ())
        report = self.issuer.issue('day')
        self.assertEqual(self.issuer.issue('day'), report)
        self.assertEqual(self.observe('SELECT report_id FROM reports'), ((report.report_id,),))
        self.assertEqual(self.observe('SELECT COUNT(*) FROM report_members'), ((2,),))
        view = ReportLookup(self.store).read(report.report_id)
        self.assertEqual([pulse.raw_count for pulse in view.pulses], [4, 5])
        self.assertEqual(view.recomputed.total, Fraction(13, 2))

    def test_empty_shift(self):
        session = self.open_shift()
        self.assertEqual(session.stop().last_pulse, 0)
        report = self.issuer.issue('day')
        self.assertEqual(report, self.issuer.issue('day'))
        self.assertEqual(report.last_pulse, 0)
        self.assertEqual(report.metrics.total, Fraction(0))
        self.assertEqual(report.metrics.exceeded_pulses, ())
        self.assertEqual(ReportLookup(self.store).read(report.report_id).pulses, ())
