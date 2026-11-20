from dataclasses import dataclass

from station.intake.conversion import Measurement, convert_reading
from station.report.archive import IssuedReport
from station.report.metrics import ReportMetrics, summarize_measurements
from station.review.evidence import InconsistentEvidenceError, ReportEvidence


@dataclass(frozen=True, slots=True)
class AuditResult:
    measurements: tuple[Measurement, ...]
    metrics: ReportMetrics


def recompute_report(report: IssuedReport, evidence: ReportEvidence) -> AuditResult:
    shift = evidence.shift
    measurements: list[Measurement] = []
    for accepted in evidence.readings:
        computed = convert_reading(accepted.raw.raw_count, shift.calibration, shift.threshold)
        if (accepted.concentration, accepted.exceeded) != (computed.concentration, computed.exceeded):
            raise InconsistentEvidenceError(f'calculation differs at pulse {accepted.raw.pulse}')
        measurements.append(computed)

    metrics = summarize_measurements(
        (accepted.raw.pulse, computed.concentration, computed.exceeded)
        for accepted, computed in zip(evidence.readings, measurements, strict=True)
    )
    if metrics != report.metrics:
        raise InconsistentEvidenceError('report summary differs from the recomputed readings')
    return AuditResult(tuple(measurements), metrics)
