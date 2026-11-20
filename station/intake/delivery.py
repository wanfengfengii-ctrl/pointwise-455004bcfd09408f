import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from station.acquisition.probe import validate_raw_count
from station.intake.encoding import (
    decode_fraction,
    decode_integer,
    encode_fraction,
    encode_integer,
)


@dataclass(frozen=True, slots=True)
class DeliveredReading:
    pulse: int
    raw_count: int
    concentration: Fraction
    exceeded: bool

    def as_dict(self) -> dict:
        return {
            'pulse': self.pulse,
            'raw_count': self.raw_count,
            'concentration': self.concentration,
            'exceeded': self.exceeded,
        }


@dataclass(frozen=True, slots=True)
class OverrunRow:
    pulse: int
    missing: str = 'overrun'

    def as_dict(self) -> dict:
        return {'pulse': self.pulse, 'missing': self.missing}


DeliveryRow = DeliveredReading | OverrunRow


@dataclass(frozen=True, slots=True)
class DeliveryBatch:
    batch_id: int
    shift_id: str
    probe_id: str
    first_pulse: int
    last_pulse: int
    rows: tuple[DeliveryRow, ...]

    def as_dict(self) -> dict:
        return {
            'batch_id': self.batch_id,
            'shift_id': self.shift_id,
            'probe_id': self.probe_id,
            'first_pulse': self.first_pulse,
            'last_pulse': self.last_pulse,
            'rows': [row.as_dict() for row in self.rows],
        }


class DeliveryLedger:
    """Durable prefix batches plus the last officially delivered pulse."""

    @staticmethod
    def cursor(connection: sqlite3.Connection, shift_id: str) -> int:
        row = connection.execute(
            'SELECT delivered_pulse FROM delivery_cursors WHERE shift_id = ?', (shift_id,)
        ).fetchone()
        if row is None:
            return 0
        delivered = decode_integer(row['delivered_pulse'])
        if delivered < 0:
            raise ValueError('stored delivery position must be nonnegative')
        return delivered

    @staticmethod
    def publish(
        connection: sqlite3.Connection,
        shift_id: str,
        probe_id: str,
        first_pulse: int,
        last_pulse: int,
        rows: list[DeliveryRow],
    ) -> DeliveryBatch:
        if not rows or rows[0].pulse != first_pulse or rows[-1].pulse != last_pulse:
            raise ValueError('delivery rows must span the batch boundaries')
        cursor = connection.execute(
            '''INSERT INTO delivery_batches (shift_id, probe_id, first_pulse, last_pulse)
               VALUES (?, ?, ?, ?)''',
            (shift_id, probe_id, encode_integer(first_pulse), encode_integer(last_pulse)),
        )
        batch_id = cursor.lastrowid
        connection.executemany(
            '''INSERT INTO delivery_rows
               (batch_id, pulse, raw_count, concentration_num, concentration_den,
                exceeded, missing)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (
                (
                    batch_id,
                    encode_integer(row.pulse),
                    None if isinstance(row, OverrunRow) else encode_integer(row.raw_count),
                    None if isinstance(row, OverrunRow) else encode_fraction(row.concentration)[0],
                    None if isinstance(row, OverrunRow) else encode_fraction(row.concentration)[1],
                    None if isinstance(row, OverrunRow) else row.exceeded,
                    row.missing if isinstance(row, OverrunRow) else None,
                )
                for row in rows
            ),
        )
        connection.execute(
            '''INSERT INTO delivery_cursors (shift_id, delivered_pulse) VALUES (?, ?)
               ON CONFLICT(shift_id) DO UPDATE SET delivered_pulse = excluded.delivered_pulse''',
            (shift_id, encode_integer(last_pulse)),
        )
        return DeliveryBatch(
            batch_id, shift_id, probe_id, first_pulse, last_pulse, tuple(rows)
        )

    @staticmethod
    def get_batch(connection: sqlite3.Connection, batch_id: int) -> DeliveryBatch | None:
        row = connection.execute(
            'SELECT * FROM delivery_batches WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        return None if row is None else DeliveryLedger._decode_batch(connection, row)

    @staticmethod
    def for_shift(
        connection: sqlite3.Connection, shift_id: str
    ) -> tuple[DeliveryBatch, ...]:
        rows = connection.execute(
            'SELECT * FROM delivery_batches WHERE shift_id = ?', (shift_id,)
        ).fetchall()
        batches = tuple(
            sorted(
                (DeliveryLedger._decode_batch(connection, row) for row in rows),
                key=lambda batch: batch.first_pulse,
            )
        )
        expected = 1
        for batch in batches:
            if batch.first_pulse != expected:
                raise ValueError('stored delivery batches do not form one prefix')
            expected = batch.last_pulse + 1
        if batches and DeliveryLedger.cursor(connection, shift_id) != batches[-1].last_pulse:
            raise ValueError('stored delivery position differs from the batches')
        return batches

    @staticmethod
    def _decode_batch(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> DeliveryBatch:
        member_rows = connection.execute(
            'SELECT * FROM delivery_rows WHERE batch_id = ?', (row['batch_id'],)
        ).fetchall()
        members = sorted(
            (DeliveryLedger._decode_row(member) for member in member_rows),
            key=lambda member: member.pulse,
        )
        first_pulse = decode_integer(row['first_pulse'])
        last_pulse = decode_integer(row['last_pulse'])
        if not members or members[0].pulse != first_pulse or members[-1].pulse != last_pulse:
            raise ValueError('stored delivery rows differ from the batch boundaries')
        return DeliveryBatch(
            row['batch_id'],
            row['shift_id'],
            row['probe_id'],
            first_pulse,
            last_pulse,
            tuple(members),
        )

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> DeliveryRow:
        pulse = decode_integer(row['pulse'])
        if pulse <= 0:
            raise ValueError('stored delivery pulse must be positive')
        if row['missing'] == 'overrun':
            if any(row[column] is not None
                   for column in ('raw_count', 'concentration_num',
                                  'concentration_den', 'exceeded')):
                raise ValueError('an overrun row must not carry a raw reading')
            return OverrunRow(pulse)
        if row['missing'] is not None:
            raise ValueError('unknown stored delivery gap')
        if row['raw_count'] is None or row['exceeded'] not in (0, 1):
            raise ValueError('a delivered reading must carry its raw result')
        return DeliveredReading(
            pulse,
            validate_raw_count(decode_integer(row['raw_count'])),
            decode_fraction(row['concentration_num'], row['concentration_den']),
            bool(row['exceeded']),
        )
