import sqlite3
from dataclasses import dataclass

from station.intake.encoding import decode_integer, encode_integer
from station.setup.shift import ShiftConflictError


CAPTURE_MODE = 'capture'
OVERRUN_MODE = 'overrun'


@dataclass(frozen=True, slots=True)
class ShiftMode:
    mode: str
    capacity: int

    @property
    def overrun(self) -> bool:
        return self.mode == OVERRUN_MODE


class ShiftModes:
    """Freeze the capture mode and pending capacity chosen when a shift opened."""

    @staticmethod
    def record(
        connection: sqlite3.Connection,
        shift_id: str,
        *,
        overrun: bool,
        capacity: int,
    ) -> ShiftMode:
        mode = OVERRUN_MODE if overrun else CAPTURE_MODE
        current = ShiftModes._find(connection, shift_id)
        if current is None:
            if mode == OVERRUN_MODE and ShiftModes._has_accepted_readings(
                connection, shift_id
            ):
                raise ShiftConflictError(shift_id)
            connection.execute(
                'INSERT INTO shift_modes (shift_id, mode, capacity) VALUES (?, ?, ?)',
                (shift_id, mode, encode_integer(capacity)),
            )
            return ShiftMode(mode, capacity)
        if current.mode != mode:
            raise ShiftConflictError(shift_id)
        if mode == OVERRUN_MODE and current.capacity != capacity:
            raise ShiftConflictError(shift_id)
        return current

    @staticmethod
    def get(
        connection: sqlite3.Connection, shift_id: str
    ) -> ShiftMode | None:
        return ShiftModes._find(connection, shift_id)

    @staticmethod
    def _find(connection: sqlite3.Connection, shift_id: str) -> ShiftMode | None:
        row = connection.execute(
            'SELECT mode, capacity FROM shift_modes WHERE shift_id = ?', (shift_id,)
        ).fetchone()
        if row is None:
            return None
        capacity = decode_integer(row['capacity'])
        if capacity <= 0 or row['mode'] not in (CAPTURE_MODE, OVERRUN_MODE):
            raise ValueError('stored shift mode is invalid')
        return ShiftMode(row['mode'], capacity)

    @staticmethod
    def _has_accepted_readings(connection: sqlite3.Connection, shift_id: str) -> bool:
        row = connection.execute(
            'SELECT 1 FROM accepted_readings WHERE shift_id = ? LIMIT 1', (shift_id,)
        ).fetchone()
        return row is not None
