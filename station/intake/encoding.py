from fractions import Fraction


def encode_integer(value: int) -> str:
    return hex(value)


def decode_integer(value: str) -> int:
    return int(value, 16)


def encode_fraction(value: Fraction) -> tuple[str, str]:
    return encode_integer(value.numerator), encode_integer(value.denominator)


def decode_fraction(numerator: str, denominator: str) -> Fraction:
    return Fraction(decode_integer(numerator), decode_integer(denominator))
