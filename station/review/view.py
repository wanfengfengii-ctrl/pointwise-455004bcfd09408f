from dataclasses import dataclass
from fractions import Fraction

from station.report.archive import IssuedReport
from station.report.metrics import ReportMetrics
from station.review.evidence import ReportEvidence
from station.review.recompute import AuditResult
from station.setup.shift import Shift


@dataclass(frozen=True, slots=True)
class PulseEvidenceView:
    ordinal: int
    shift_id: str
    probe_id: str
    pulse: int
    raw_count: int
    receipt_id: int
    concentration: Fraction
    exceeded: bool


@dataclass(frozen=True, slots=True)
class AuditView:
    report: IssuedReport
    shift: Shift
    pulses: tuple[PulseEvidenceView, ...]
    recomputed: ReportMetrics


def make_audit_view(report: IssuedReport, evidence: ReportEvidence, audit: AuditResult) -> AuditView:
    pulses = tuple(
        PulseEvidenceView(
            ordinal,
            accepted.raw.shift_id,
            accepted.raw.probe_id,
            accepted.raw.pulse,
            accepted.raw.raw_count,
            accepted.receipt.receipt_id,
            computed.concentration,
            computed.exceeded,
        )
        for ordinal, (accepted, computed) in enumerate(
            zip(evidence.readings, audit.measurements, strict=True), start=1
        )
    )
    return AuditView(report, evidence.shift, pulses, audit.metrics)
