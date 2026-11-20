import sqlite3
from dataclasses import dataclass

from station.intake.records import AcceptedReading, AcceptedRecords
from station.report.archive import IssuedReport, ReportArchive
from station.report.close import get_stop
from station.setup.shift import Shift, ShiftRegistry


class InconsistentEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReportEvidence:
    shift: Shift
    readings: tuple[AcceptedReading, ...]


def load_report_evidence(
    connection: sqlite3.Connection, report: IssuedReport, registry: ShiftRegistry
) -> ReportEvidence:
    shift = registry.get(report.shift_id, connection=connection)
    stop = get_stop(connection, report.shift_id)
    if not shift.stopped or stop is None or stop.last_pulse != report.last_pulse:
        raise InconsistentEvidenceError('archived bounds differ from the recorded stop')
    keys = ReportArchive.member_keys(connection, report.report_id)
    if len(keys) != stop.last_pulse:
        raise InconsistentEvidenceError('archived member count differs from the recorded stop')

    readings: list[AcceptedReading] = []
    for expected_pulse, key in enumerate(keys, start=1):
        if (key.ordinal, key.source_shift_id, key.source_pulse) != (
            expected_pulse, shift.shift_id, expected_pulse
        ):
            raise InconsistentEvidenceError(f'invalid member reference at position {expected_pulse}')
        record = AcceptedRecords.get(connection, key.source_shift_id, key.source_pulse)
        if record is None:
            raise InconsistentEvidenceError(f'missing accepted reading at pulse {expected_pulse}')
        if record.raw.probe_id != shift.probe.probe_id:
            raise InconsistentEvidenceError(f'probe identity differs at pulse {expected_pulse}')
        readings.append(record)
    return ReportEvidence(shift, tuple(readings))
