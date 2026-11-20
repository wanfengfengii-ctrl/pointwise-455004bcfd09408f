from station.acquisition.session import AcquisitionSession
from station.intake.admit import AdmissionService
from station.intake.records import AcceptedReading


class PendingReadingError(LookupError):
    pass


class ReadingDispatch:
    def __init__(self, admission: AdmissionService) -> None:
        self._admission = admission

    def deliver(self, session: AcquisitionSession, pulse: int) -> AcceptedReading:
        reading = session.pending_reading(pulse)
        if reading is None:
            raise PendingReadingError(pulse)
        accepted = self._admission.admit(reading)
        session.confirm(accepted.receipt)
        return accepted
