from dataclasses import dataclass

from station.acquisition.clock import PulseToken


@dataclass(frozen=True, slots=True)
class RawReading:
    shift_id: str
    probe_id: str
    pulse: int
    raw_count: int


def validate_raw_count(raw_count: int) -> int:
    if type(raw_count) is not int or raw_count < 0:
        raise ValueError('raw_count must be a nonnegative integer')
    return raw_count


def reading_from_completion(token: PulseToken, raw_count: int) -> RawReading:
    return RawReading(token.shift_id, token.probe_id, token.pulse, validate_raw_count(raw_count))
