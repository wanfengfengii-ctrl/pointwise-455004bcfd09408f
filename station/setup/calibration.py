from dataclasses import dataclass
from fractions import Fraction


RationalInput = Fraction | int | str


def parse_rational(value: RationalInput) -> Fraction:
    if type(value) is not int and not isinstance(value, (Fraction, str)):
        raise ValueError('a rational must be an integer, Fraction, or exact numeric string')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('invalid rational value') from exc


@dataclass(frozen=True, slots=True)
class Calibration:
    multiplier: Fraction
    offset: Fraction

    def __post_init__(self) -> None:
        multiplier = parse_rational(self.multiplier)
        offset = parse_rational(self.offset)
        if multiplier <= 0:
            raise ValueError('calibration multiplier must be positive')
        object.__setattr__(self, 'multiplier', multiplier)
        object.__setattr__(self, 'offset', offset)

    def apply(self, raw_count: int) -> Fraction:
        return raw_count * self.multiplier + self.offset
