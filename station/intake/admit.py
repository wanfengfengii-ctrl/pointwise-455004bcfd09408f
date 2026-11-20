from station.acquisition.probe import RawReading, validate_raw_count
from station.intake.conversion import convert_reading
from station.intake.delivery import DeliveredReading, DeliveryBatch, DeliveryLedger
from station.intake.records import AcceptedReading, AcceptedRecords
from station.intake.store import StationStore
from station.setup.shift import Shift, ShiftRegistry


class AdmissionConflictError(ValueError):
    pass


class UnknownBatchError(LookupError):
    pass


class AdmissionService:
    def __init__(self, store: StationStore) -> None:
        self._store = store
        self._registry = ShiftRegistry(store)

    @property
    def store(self) -> StationStore:
        return self._store

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

    def read_prefix(self, shift_id: str) -> list[dict]:
        """Every pulse officially delivered for the shift, in pulse order."""

        with self._store.snapshot() as connection:
            shift = self._registry.get(shift_id, connection=connection)
            batches = DeliveryLedger.for_shift(connection, shift_id)
        rows: list[dict] = []
        for batch in batches:
            self._verify_batch(batch, shift)
            rows.extend(row.as_dict() for row in batch.rows)
        return rows

    def read_batch(self, batch_id: int) -> dict:
        """One fixed delivery batch, with the same shape as the delivery result."""

        if type(batch_id) is not int or not 0 < batch_id < 2**63:
            raise UnknownBatchError(batch_id)
        with self._store.snapshot() as connection:
            batch = DeliveryLedger.get_batch(connection, batch_id)
            if batch is None:
                raise UnknownBatchError(batch_id)
            shift = self._registry.get(batch.shift_id, connection=connection)
        self._verify_batch(batch, shift)
        return batch.as_dict()

    @staticmethod
    def _verify_batch(batch: DeliveryBatch, shift: Shift) -> None:
        """Re-apply the frozen calibration so a fixed batch cannot drift from its raw reads."""

        if batch.probe_id != shift.probe.probe_id:
            raise ValueError(f'batch {batch.batch_id} carries a different probe')
        for row in batch.rows:
            if not isinstance(row, DeliveredReading):
                continue
            measurement = convert_reading(row.raw_count, shift.calibration, shift.threshold)
            if (row.concentration, row.exceeded) != (measurement.concentration, measurement.exceeded):
                raise ValueError(f'batch {batch.batch_id} differs at pulse {row.pulse}')
