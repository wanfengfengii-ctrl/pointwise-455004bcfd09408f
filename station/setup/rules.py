from dataclasses import dataclass
from fractions import Fraction


CONCENTRATION_UNIT = 'μg/m³'


@dataclass(frozen=True, slots=True)
class ThresholdRule:
    limit: Fraction

    def is_exceeded(self, concentration: Fraction) -> bool:
        return concentration > self.limit
