from station.intake.records import AcceptedRecords
from station.intake.store import StationStore
from station.report.archive import IssuedReport, ReportArchive
from station.report.close import get_stop
from station.report.coverage import select_report_members
from station.report.metrics import summarize_measurements
from station.setup.shift import ShiftRegistry


class ShiftNotStoppedError(RuntimeError):
    pass


class ReportIssuer:
    def __init__(self, store: StationStore) -> None:
        self._store = store
        self._registry = ShiftRegistry(store)

    def issue(self, shift_id: str) -> IssuedReport:
        with self._store.transaction('issue') as connection:
            shift = self._registry.get(shift_id, connection=connection)
            stop = get_stop(connection, shift_id)
            if not shift.stopped or stop is None:
                raise ShiftNotStoppedError(shift_id)
            previous = ReportArchive.get_by_shift(connection, shift_id)
            if previous is not None:
                return previous
            members = select_report_members(
                shift_id, shift.probe.probe_id, stop.last_pulse,
                AcceptedRecords.for_shift(connection, shift_id),
            )
            metrics = summarize_measurements(
                (member.raw.pulse, member.concentration, member.exceeded) for member in members
            )
            return ReportArchive.publish(
                connection, shift_id, stop.last_pulse, metrics,
                ((member.raw.shift_id, member.raw.pulse) for member in members),
            )
