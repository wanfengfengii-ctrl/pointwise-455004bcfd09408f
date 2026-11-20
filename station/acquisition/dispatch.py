from station.acquisition.clock import AcquisitionStateError
from station.acquisition.probe import RawReading
from station.acquisition.session import AcquisitionSession
from station.intake.admit import AdmissionService
from station.intake.conversion import convert_reading
from station.intake.delivery import (
    DeliveredReading,
    DeliveryBatch,
    DeliveryLedger,
    DeliveryRow,
    OverrunRow,
)
from station.intake.records import AcceptedReading
from station.setup.shift import ShiftRegistry


class PendingReadingError(LookupError):
    pass


class ReadingDispatch:
    def __init__(self, admission: AdmissionService) -> None:
        self._admission = admission
        self._registry = ShiftRegistry(admission.store)

    def deliver(self, session: AcquisitionSession, pulse: int) -> AcceptedReading:
        if session.overrun:
            raise AcquisitionStateError(
                'an overrun shift delivers whole prefixes instead of single readings'
            )
        reading = session.pending_reading(pulse)
        if reading is None:
            raise PendingReadingError(pulse)
        accepted = self._admission.admit(reading)
        session.confirm(accepted.receipt)
        return accepted

    def deliver_prefix(self, session: AcquisitionSession) -> dict | None:
        """Take over every completed pulse since the last official delivery, as one batch."""

        if not session.overrun:
            raise AcquisitionStateError('prefix delivery requires an overrun shift')
        with session.delivery_guard():
            completed, held = session.delivery_evidence()
            cursor, batch = self._publish(session, completed, held)
            if batch is None:
                # A batch may already have committed while its slot release did not run;
                # free those taken-over reads now and report no new batch.
                session.release_through(cursor)
                return None
            session.release_through(batch.last_pulse)
            return batch.as_dict()

    def _publish(
        self,
        session: AcquisitionSession,
        completed: int,
        held: tuple[RawReading, ...],
    ) -> tuple[int, DeliveryBatch | None]:
        shift_id = session.shift_id
        held_by_pulse = {reading.pulse: reading for reading in held}
        rows: list[DeliveryRow] = []
        with self._admission.store.transaction('deliver_prefix') as connection:
            cursor = DeliveryLedger.cursor(connection, shift_id)
            if completed <= cursor:
                return cursor, None
            shift = self._registry.get(shift_id, connection=connection)
            for pulse in range(cursor + 1, completed + 1):
                reading = held_by_pulse.get(pulse)
                if reading is None:
                    rows.append(OverrunRow(pulse))
                    continue
                if reading.shift_id != shift_id or reading.probe_id != shift.probe.probe_id:
                    raise ValueError(f'held reading at pulse {pulse} differs from the shift')
                measurement = convert_reading(
                    reading.raw_count, shift.calibration, shift.threshold
                )
                rows.append(
                    DeliveredReading(
                        pulse,
                        reading.raw_count,
                        measurement.concentration,
                        measurement.exceeded,
                    )
                )
            batch = DeliveryLedger.publish(
                connection, shift_id, shift.probe.probe_id, cursor + 1, completed, rows
            )
            return cursor, batch
