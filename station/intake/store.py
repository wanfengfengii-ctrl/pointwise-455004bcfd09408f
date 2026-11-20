import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shifts (
        shift_id TEXT NOT NULL PRIMARY KEY,
        probe_id TEXT NOT NULL,
        multiplier_num TEXT NOT NULL,
        multiplier_den TEXT NOT NULL,
        offset_num TEXT NOT NULL,
        offset_den TEXT NOT NULL,
        limit_num TEXT NOT NULL,
        limit_den TEXT NOT NULL,
        stopped INTEGER NOT NULL DEFAULT 0 CHECK (stopped IN (0, 1))
    )''',
    '''CREATE TABLE IF NOT EXISTS shift_stops (
        shift_id TEXT NOT NULL PRIMARY KEY REFERENCES shifts(shift_id),
        last_pulse TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS accepted_readings (
        receipt_id INTEGER PRIMARY KEY,
        shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
        probe_id TEXT NOT NULL,
        pulse TEXT NOT NULL,
        raw_count TEXT NOT NULL,
        concentration_num TEXT NOT NULL,
        concentration_den TEXT NOT NULL,
        exceeded INTEGER NOT NULL CHECK (exceeded IN (0, 1)),
        UNIQUE (shift_id, pulse)
    )''',
    '''CREATE TABLE IF NOT EXISTS reports (
        report_id INTEGER PRIMARY KEY,
        shift_id TEXT NOT NULL UNIQUE REFERENCES shift_stops(shift_id),
        last_pulse TEXT NOT NULL,
        total_num TEXT NOT NULL,
        total_den TEXT NOT NULL,
        exceeded_pulses TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS report_members (
        report_id INTEGER NOT NULL REFERENCES reports(report_id),
        ordinal TEXT NOT NULL,
        source_shift_id TEXT NOT NULL,
        source_pulse TEXT NOT NULL,
        PRIMARY KEY (report_id, ordinal),
        UNIQUE (report_id, source_shift_id, source_pulse),
        FOREIGN KEY (source_shift_id, source_pulse)
            REFERENCES accepted_readings(shift_id, pulse)
    )''',
)


class StationStore:
    def __init__(
        self,
        path: str | Path,
        *,
        before_commit: Callable[[str], None] | None = None,
    ) -> None:
        self._lock = RLock()
        self._before_commit = before_commit
        connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
        except BaseException:
            connection.close()
            raise
        self._connection: sqlite3.Connection | None = connection

    def __enter__(self) -> 'StationStore':
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def initialize(self) -> None:
        with self.transaction('initialize') as connection:
            for statement in _SCHEMA:
                connection.execute(statement)

    @contextmanager
    def _scope(self, begin: str) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connection
            if connection is None:
                raise RuntimeError('station store is closed')
            if connection.in_transaction:
                raise RuntimeError('use the current connection for nested station work')
            connection.execute(begin)
            try:
                yield connection
            finally:
                if connection.in_transaction:
                    connection.rollback()

    @contextmanager
    def transaction(self, operation: str) -> Iterator[sqlite3.Connection]:
        with self._scope('BEGIN IMMEDIATE') as connection:
            changes_before = connection.total_changes
            yield connection
            if self._before_commit is not None and connection.total_changes != changes_before:
                self._before_commit(operation)
            connection.commit()

    @contextmanager
    def snapshot(self) -> Iterator[sqlite3.Connection]:
        with self._scope('BEGIN') as connection:
            connection.execute('PRAGMA query_only = ON')
            try:
                yield connection
            finally:
                connection.execute('PRAGMA query_only = OFF')

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                if self._connection.in_transaction:
                    raise RuntimeError('close the store after the current operation')
                self._connection.close()
                self._connection = None
