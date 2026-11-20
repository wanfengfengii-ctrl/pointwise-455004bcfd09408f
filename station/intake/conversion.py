from dataclasses import dataclass
from fractions import Fraction

from station.setup.calibration import Calibration
from station.setup.rules import CONCENTRATION_UNIT, ThresholdRule


@dataclass(frozen=True, slots=True)
class Measurement:
    concentration: Fraction
    exceeded: bool

    @property
    def unit(self) -> str:
        return CONCENTRATION_UNIT


def convert_reading(
    raw_count: int, calibration: Calibration, threshold: ThresholdRule
) -> Measurement:
    concentration = calibration.apply(raw_count)
    return Measurement(concentration, threshold.is_exceeded(concentration))
