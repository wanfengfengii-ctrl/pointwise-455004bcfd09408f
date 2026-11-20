from collections.abc import Iterable

from station.intake.records import AcceptedReading


class IncompleteCoverageError(RuntimeError):
    pass


def select_report_members(
    shift_id: str,
    probe_id: str,
    last_pulse: int,
    records: Iterable[AcceptedReading],
) -> tuple[AcceptedReading, ...]:
    ordered = tuple(sorted(records, key=lambda record: record.raw.pulse))
    if len(ordered) != last_pulse:
        raise IncompleteCoverageError(
            f'shift {shift_id} has {len(ordered)} records for {last_pulse} pulses'
        )
    for pulse, record in enumerate(ordered, start=1):
        raw = record.raw
        if (raw.shift_id, raw.probe_id, raw.pulse) != (shift_id, probe_id, pulse):
            raise IncompleteCoverageError(f'shift {shift_id} lacks a compatible member at pulse {pulse}')
    return ordered
