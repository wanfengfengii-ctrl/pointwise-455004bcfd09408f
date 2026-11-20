from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from station.setup.rules import CONCENTRATION_UNIT


@dataclass(frozen=True, slots=True)
class ReportMetrics:
    total: Fraction
    exceeded_pulses: tuple[int, ...]

    @property
    def unit(self) -> str:
        return CONCENTRATION_UNIT


def summarize_measurements(
    measurements: Iterable[tuple[int, Fraction, bool]],
) -> ReportMetrics:
    total = Fraction(0)
    exceeded_pulses: list[int] = []
    for pulse, concentration, exceeded in measurements:
        total += concentration
        if exceeded:
            exceeded_pulses.append(pulse)
    return ReportMetrics(total, tuple(exceeded_pulses))
