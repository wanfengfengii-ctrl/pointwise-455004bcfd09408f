from dataclasses import dataclass


class AcquisitionStateError(RuntimeError):
    pass


class PulseInProgressError(AcquisitionStateError):
    pass


class InvalidPulseTokenError(AcquisitionStateError):
    pass


class CaptureStoppedError(AcquisitionStateError):
    pass


@dataclass(frozen=True, slots=True, eq=False)
class PulseToken:
    shift_id: str
    probe_id: str
    pulse: int


class PulseClock:
    def __init__(self, shift_id: str, probe_id: str) -> None:
        self._shift_id = shift_id
        self._probe_id = probe_id
        self._last_pulse = 0
        self._active: PulseToken | None = None
        self._sealed = False

    @property
    def last_pulse(self) -> int:
        return self._last_pulse

    def require_open(self) -> None:
        if self._sealed:
            raise CaptureStoppedError(self._shift_id)

    def require_idle(self) -> None:
        if self._active is not None:
            raise PulseInProgressError(self._active.pulse)

    def begin(self) -> PulseToken:
        self.require_open()
        self.require_idle()
        next_pulse = self._last_pulse + 1
        token = PulseToken(self._shift_id, self._probe_id, next_pulse)
        self._last_pulse = next_pulse
        self._active = token
        return token

    def require_active(self, token: PulseToken) -> PulseToken:
        if self._active is None or token is not self._active:
            raise InvalidPulseTokenError('completion requires the current in-flight token')
        return self._active

    def complete(self, token: PulseToken) -> None:
        self.require_active(token)
        self._active = None

    def seal(self) -> int:
        self.require_open()
        self.require_idle()
        self._sealed = True
        return self._last_pulse
