import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from station.intake.encoding import decode_fraction, decode_integer, encode_fraction, encode_integer
from station.report.metrics import ReportMetrics


@dataclass(frozen=True, slots=True)
class IssuedReport:
    report_id: int
    shift_id: str
    last_pulse: int
    metrics: ReportMetrics


@dataclass(frozen=True, slots=True)
class MemberKey:
    ordinal: int
    source_shift_id: str
    source_pulse: int


class ReportArchive:
    @staticmethod
    def publish(
        connection: sqlite3.Connection,
        shift_id: str,
        last_pulse: int,
        metrics: ReportMetrics,
        keys: Iterable[tuple[str, int]],
    ) -> IssuedReport:
        cursor = connection.execute(
            '''INSERT INTO reports
               (shift_id, last_pulse, total_num, total_den, exceeded_pulses)
               VALUES (?, ?, ?, ?, ?)''',
            (
                shift_id,
                encode_integer(last_pulse),
                *encode_fraction(metrics.total),
                json.dumps([encode_integer(pulse) for pulse in metrics.exceeded_pulses]),
            ),
        )
        report_id = cursor.lastrowid
        connection.executemany(
            '''INSERT INTO report_members (report_id, ordinal, source_shift_id, source_pulse)
               VALUES (?, ?, ?, ?)''',
            (
                (report_id, encode_integer(ordinal), source_shift, encode_integer(pulse))
                for ordinal, (source_shift, pulse) in enumerate(keys, start=1)
            ),
        )
        return IssuedReport(report_id, shift_id, last_pulse, metrics)

    @staticmethod
    def get(connection: sqlite3.Connection, report_id: int) -> IssuedReport | None:
        row = connection.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,)).fetchone()
        return None if row is None else ReportArchive._decode(row)

    @staticmethod
    def get_by_shift(connection: sqlite3.Connection, shift_id: str) -> IssuedReport | None:
        row = connection.execute('SELECT * FROM reports WHERE shift_id = ?', (shift_id,)).fetchone()
        return None if row is None else ReportArchive._decode(row)

    @staticmethod
    def member_keys(connection: sqlite3.Connection, report_id: int) -> tuple[MemberKey, ...]:
        rows = connection.execute(
            '''SELECT ordinal, source_shift_id, source_pulse
               FROM report_members WHERE report_id = ?''',
            (report_id,),
        )
        keys = [
            MemberKey(decode_integer(row['ordinal']), row['source_shift_id'],
                      decode_integer(row['source_pulse']))
            for row in rows
        ]
        return tuple(sorted(keys, key=lambda key: key.ordinal))

    @staticmethod
    def _decode(row: sqlite3.Row) -> IssuedReport:
        encoded_pulses = json.loads(row['exceeded_pulses'])
        if not isinstance(encoded_pulses, list):
            raise ValueError('report grades must be an ordered pulse list')
        metrics = ReportMetrics(
            decode_fraction(row['total_num'], row['total_den']),
            tuple(decode_integer(pulse) for pulse in encoded_pulses),
        )
        return IssuedReport(
            row['report_id'], row['shift_id'], decode_integer(row['last_pulse']), metrics
        )
