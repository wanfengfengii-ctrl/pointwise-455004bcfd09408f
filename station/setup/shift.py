import sqlite3
from dataclasses import dataclass

from station.intake.encoding import decode_fraction, decode_integer, encode_fraction
from station.intake.store import StationStore
from station.setup.calibration import Calibration, RationalInput, parse_rational
from station.setup.probe import ProbeIdentity
from station.setup.rules import ThresholdRule


class UnknownShiftError(LookupError):
    pass


class ShiftConflictError(ValueError):
    pass


class ShiftAlreadyStoppedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Shift:
    shift_id: str
    probe: ProbeIdentity
    calibration: Calibration
    threshold: ThresholdRule
    stopped: bool = False
    last_pulse: int | None = None


class ShiftRegistry:
    def __init__(self, store: StationStore) -> None:
        self._store = store

    def open(
        self,
        shift_id: str,
        probe_id: str,
        multiplier: RationalInput,
        offset: RationalInput,
        limit: RationalInput,
    ) -> Shift:
        if not isinstance(shift_id, str) or not shift_id.strip():
            raise ValueError('shift_id must be a nonblank string')
        probe = ProbeIdentity(probe_id)
        calibration = Calibration(parse_rational(multiplier), parse_rational(offset))
        threshold = ThresholdRule(parse_rational(limit))
        with self._store.transaction('open') as connection:
            previous = self._find(connection, shift_id)
            if previous is not None:
                if (previous.probe, previous.calibration, previous.threshold) != (
                    probe, calibration, threshold
                ):
                    raise ShiftConflictError(shift_id)
                return previous
            connection.execute(
                '''INSERT INTO shifts
                   (shift_id, probe_id, multiplier_num, multiplier_den,
                    offset_num, offset_den, limit_num, limit_den)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    shift_id,
                    probe.probe_id,
                    *encode_fraction(calibration.multiplier),
                    *encode_fraction(calibration.offset),
                    *encode_fraction(threshold.limit),
                ),
            )
            return Shift(shift_id, probe, calibration, threshold)

    def get(self, shift_id: str, *, connection: sqlite3.Connection | None = None) -> Shift:
        if connection is None:
            with self._store.snapshot() as snapshot:
                return self.get(shift_id, connection=snapshot)
        shift = self._find(connection, shift_id)
        if shift is None:
            raise UnknownShiftError(shift_id)
        return shift

    def mark_stopped(self, connection: sqlite3.Connection, shift_id: str) -> None:
        cursor = connection.execute(
            'UPDATE shifts SET stopped = 1 WHERE shift_id = ? AND stopped = 0', (shift_id,)
        )
        if cursor.rowcount == 0:
            self.get(shift_id, connection=connection)
            raise ShiftAlreadyStoppedError(shift_id)

    @staticmethod
    def _find(connection: sqlite3.Connection, shift_id: str) -> Shift | None:
        row = connection.execute(
            '''SELECT s.*, t.last_pulse
               FROM shifts AS s LEFT JOIN shift_stops AS t USING (shift_id)
               WHERE s.shift_id = ?''',
            (shift_id,),
        ).fetchone()
        if row is None:
            return None
        last_pulse = row['last_pulse']
        return Shift(
            row['shift_id'],
            ProbeIdentity(row['probe_id']),
            Calibration(
                decode_fraction(row['multiplier_num'], row['multiplier_den']),
                decode_fraction(row['offset_num'], row['offset_den']),
            ),
            ThresholdRule(decode_fraction(row['limit_num'], row['limit_den'])),
            bool(row['stopped']),
            None if last_pulse is None else decode_integer(last_pulse),
        )
