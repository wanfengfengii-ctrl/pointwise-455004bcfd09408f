from threading import Lock

from station.acquisition.clock import (
    AcquisitionStateError,
    CaptureStoppedError,
    PulseClock,
    PulseToken,
)
from station.acquisition.probe import RawReading, reading_from_completion
from station.acquisition.queue import PendingQueue, QueueFullError, validate_capacity
from station.intake.receipts import AdmissionReceipt
from station.intake.store import StationStore
from station.report.close import StopRecord, record_stop
from station.setup.calibration import RationalInput
from station.setup.shift import Shift, ShiftRegistry


class AcquisitionSession:
    def __init__(self, store: StationStore, shift: Shift, capacity: int) -> None:
        if shift.stopped:
            raise CaptureStoppedError(shift.shift_id)
        self._store = store
        self._shift_id = shift.shift_id
        self._clock = PulseClock(shift.shift_id, shift.probe.probe_id)
        self._pending = PendingQueue(capacity)
        self._lock = Lock()
        self._stopping = False

    def _require_running(self) -> None:
        self._clock.require_open()
        if self._stopping:
            raise AcquisitionStateError('a stop is pending commit')

    def start(self) -> PulseToken:
        with self._lock:
            self._require_running()
            self._clock.require_idle()
            if self._pending.is_full():
                raise QueueFullError('deliver a pending reading before starting another pulse')
            return self._clock.begin()

    def finish(self, token: PulseToken, raw_count: int) -> RawReading:
        with self._lock:
            active = self._clock.require_active(token)
            reading = reading_from_completion(active, raw_count)
            self._pending.retain(reading)
            self._clock.complete(active)
            return reading

    def pending_reading(self, pulse: int) -> RawReading | None:
        with self._lock:
            return self._pending.get(pulse)

    def confirm(self, receipt: AdmissionReceipt) -> bool:
        with self._lock:
            reading = self._pending.get(receipt.raw.pulse)
            if reading is None or not receipt.matches(reading):
                return False
            return self._pending.release(reading)

    def stop(self) -> StopRecord:
        with self._lock:
            self._require_running()
            self._clock.require_idle()
            last_pulse = self._clock.last_pulse
            self._stopping = True

        # Guard the stop boundary while leaving pending reads accessible during SQLite I/O.
        try:
            stop = record_stop(self._store, self._shift_id, last_pulse)
        except BaseException:
            with self._lock:
                self._stopping = False
            raise

        with self._lock:
            self._clock.seal()
            self._stopping = False
        return stop


class AcquisitionBridge:
    """Own the sessions for one running station bridge."""

    def __init__(self, store: StationStore, capacity: int) -> None:
        self._capacity = validate_capacity(capacity)
        self._store = store
        self._registry = ShiftRegistry(store)
        self._sessions: dict[str, AcquisitionSession] = {}
        self._lock = Lock()

    def open(
        self,
        shift_id: str,
        probe_id: str,
        multiplier: RationalInput,
        offset: RationalInput,
        limit: RationalInput,
    ) -> Shift:
        shift = self._registry.open(shift_id, probe_id, multiplier, offset, limit)
        with self._lock:
            if shift_id not in self._sessions and not shift.stopped:
                self._sessions[shift_id] = AcquisitionSession(self._store, shift, self._capacity)
        return shift

    def session(self, shift_id: str) -> AcquisitionSession:
        with self._lock:
            return self._sessions[shift_id]
