import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from station.acquisition.probe import RawReading, validate_raw_count
from station.intake.encoding import decode_fraction, decode_integer, encode_fraction, encode_integer
from station.intake.receipts import AdmissionReceipt, receipt_from_admission


@dataclass(frozen=True, slots=True)
class AcceptedReading:
    raw: RawReading
    concentration: Fraction
    exceeded: bool
    receipt: AdmissionReceipt


class AcceptedRecords:
    @staticmethod
    def insert(
        connection: sqlite3.Connection,
        raw: RawReading,
        concentration: Fraction,
        exceeded: bool,
    ) -> AcceptedReading:
        cursor = connection.execute(
            '''INSERT INTO accepted_readings
               (shift_id, probe_id, pulse, raw_count,
                concentration_num, concentration_den, exceeded)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (
                raw.shift_id,
                raw.probe_id,
                encode_integer(raw.pulse),
                encode_integer(raw.raw_count),
                *encode_fraction(concentration),
                exceeded,
            ),
        )
        receipt = receipt_from_admission(cursor.lastrowid, raw)
        return AcceptedReading(raw, concentration, exceeded, receipt)

    @staticmethod
    def get(
        connection: sqlite3.Connection, shift_id: str, pulse: int
    ) -> AcceptedReading | None:
        row = connection.execute(
            'SELECT * FROM accepted_readings WHERE shift_id = ? AND pulse = ?',
            (shift_id, encode_integer(pulse)),
        ).fetchone()
        return None if row is None else AcceptedRecords._decode(row)

    @staticmethod
    def for_shift(connection: sqlite3.Connection, shift_id: str) -> tuple[AcceptedReading, ...]:
        rows = connection.execute(
            'SELECT * FROM accepted_readings WHERE shift_id = ? ORDER BY receipt_id',
            (shift_id,),
        )
        return tuple(AcceptedRecords._decode(row) for row in rows)

    @staticmethod
    def _decode(row: sqlite3.Row) -> AcceptedReading:
        pulse = decode_integer(row['pulse'])
        count = validate_raw_count(decode_integer(row['raw_count']))
        if pulse <= 0 or row['exceeded'] not in (0, 1):
            raise ValueError('invalid durable pulse or grade')
        raw = RawReading(row['shift_id'], row['probe_id'], pulse, count)
        return AcceptedReading(
            raw,
            decode_fraction(row['concentration_num'], row['concentration_den']),
            bool(row['exceeded']),
            receipt_from_admission(row['receipt_id'], raw),
        )
