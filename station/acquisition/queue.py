from station.acquisition.clock import AcquisitionStateError
from station.acquisition.probe import RawReading


class QueueFullError(AcquisitionStateError):
    pass


def validate_capacity(capacity: int) -> int:
    if type(capacity) is not int or capacity <= 0:
        raise ValueError('pending capacity must be a positive integer')
    return capacity


class PendingQueue:
    def __init__(self, capacity: int) -> None:
        self._capacity = validate_capacity(capacity)
        self._slots: dict[int, RawReading] = {}

    def is_full(self) -> bool:
        return len(self._slots) >= self._capacity

    def retain(self, reading: RawReading) -> None:
        if reading.pulse in self._slots:
            raise AcquisitionStateError('the pulse already occupies a pending slot')
        if self.is_full():
            raise QueueFullError('all pending slots are occupied')
        self._slots[reading.pulse] = reading

    def get(self, pulse: int) -> RawReading | None:
        return self._slots.get(pulse)

    def release(self, reading: RawReading) -> bool:
        if self._slots.get(reading.pulse) != reading:
            return False
        del self._slots[reading.pulse]
        return True
