import sqlite3
from dataclasses import dataclass

from station.intake.encoding import decode_integer, encode_integer
from station.intake.store import StationStore
from station.setup.shift import ShiftRegistry


@dataclass(frozen=True, slots=True)
class StopRecord:
    shift_id: str
    last_pulse: int


def record_stop(store: StationStore, shift_id: str, last_pulse: int) -> StopRecord:
    if type(last_pulse) is not int or last_pulse < 0:
        raise ValueError('last_pulse must be a nonnegative integer')
    with store.transaction('stop') as connection:
        ShiftRegistry(store).mark_stopped(connection, shift_id)
        connection.execute(
            'INSERT INTO shift_stops (shift_id, last_pulse) VALUES (?, ?)',
            (shift_id, encode_integer(last_pulse)),
        )
    return StopRecord(shift_id, last_pulse)


def get_stop(connection: sqlite3.Connection, shift_id: str) -> StopRecord | None:
    row = connection.execute(
        'SELECT last_pulse FROM shift_stops WHERE shift_id = ?', (shift_id,)
    ).fetchone()
    if row is None:
        return None
    last_pulse = decode_integer(row['last_pulse'])
    if last_pulse < 0:
        raise ValueError('stored stop pulse must be nonnegative')
    return StopRecord(shift_id, last_pulse)
