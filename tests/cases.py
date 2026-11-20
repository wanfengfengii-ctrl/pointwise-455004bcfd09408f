import json
from fractions import Fraction
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / 'examples' / 'overload_cases.json'


def load_cases() -> dict:
    with CASES.open(encoding='utf-8') as handle:
        return json.load(handle)


def expected_rows(rows: list[dict]) -> list[dict]:
    return [
        row if 'missing' in row else {**row, 'concentration': Fraction(row['concentration'])}
        for row in rows
    ]
