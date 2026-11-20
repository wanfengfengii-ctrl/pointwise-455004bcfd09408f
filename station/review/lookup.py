from station.intake.store import StationStore
from station.report.archive import ReportArchive
from station.review.evidence import InconsistentEvidenceError, load_report_evidence
from station.review.recompute import recompute_report
from station.review.view import AuditView, make_audit_view
from station.setup.shift import ShiftRegistry, UnknownShiftError


class UnknownReportError(LookupError):
    pass


class ReportLookup:
    def __init__(self, store: StationStore) -> None:
        self._store = store
        self._registry = ShiftRegistry(store)

    def read(self, report_id: int) -> AuditView:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            raise UnknownReportError(report_id)
        with self._store.snapshot() as connection:
            try:
                report = ReportArchive.get(connection, report_id)
                if report is None:
                    raise UnknownReportError(report_id)
                evidence = load_report_evidence(connection, report, self._registry)
                audit = recompute_report(report, evidence)
                return make_audit_view(report, evidence, audit)
            except (ValueError, TypeError, ZeroDivisionError, UnknownShiftError) as exc:
                raise InconsistentEvidenceError(f'invalid stored evidence for report {report_id}') from exc
