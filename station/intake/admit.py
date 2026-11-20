from station.acquisition.probe import RawReading, validate_raw_count
from station.intake.conversion import convert_reading
from station.intake.records import AcceptedReading, AcceptedRecords
from station.intake.store import StationStore
from station.setup.shift import ShiftRegistry


class AdmissionConflictError(ValueError):
    pass


class AdmissionService:
    def __init__(self, store: StationStore) -> None:
        self._store = store
        self._registry = ShiftRegistry(store)

    def admit(self, raw: RawReading) -> AcceptedReading:
        if not isinstance(raw, RawReading):
            raise TypeError('admit requires a named raw reading')
        if not isinstance(raw.shift_id, str) or not raw.shift_id.strip():
            raise ValueError('shift_id must be a nonblank string')
        if type(raw.pulse) is not int or raw.pulse <= 0:
            raise ValueError('pulse must be a positive integer')
        validate_raw_count(raw.raw_count)

        with self._store.transaction('admit') as connection:
            shift = self._registry.get(raw.shift_id, connection=connection)
            if raw.probe_id != shift.probe.probe_id:
                raise AdmissionConflictError('reading probe differs from the frozen shift probe')
            if shift.stopped and (shift.last_pulse is None or raw.pulse > shift.last_pulse):
                raise AdmissionConflictError('reading lies beyond the recorded stop')
            previous = AcceptedRecords.get(connection, raw.shift_id, raw.pulse)
            if previous is not None:
                if previous.raw != raw:
                    raise AdmissionConflictError('the shift and pulse already have a different reading')
                return previous
            measurement = convert_reading(raw.raw_count, shift.calibration, shift.threshold)
            return AcceptedRecords.insert(connection, raw, measurement.concentration, measurement.exceeded)
