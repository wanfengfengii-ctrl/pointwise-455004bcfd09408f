import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock

from station.acquisition.dispatch import ReadingDispatch
from station.acquisition.session import AcquisitionBridge
from station.intake.admit import AdmissionService
from station.intake.store import StationStore
from station.report.issue import ReportIssuer
from station.review.lookup import ReportLookup


class CommitRejected(RuntimeError):
    pass


class CommitBoundary:
    def __init__(self, operation, pause, fail):
        self.operation = operation
        self.pause = pause
        self.fail = fail
        self.reached = Event()
        self.resume = Event()

    def wait(self):
        if not self.reached.wait(10):
            raise AssertionError(f'{self.operation} did not reach the commit boundary')

    def arrive(self):
        self.reached.set()
        if self.pause and not self.resume.wait(10):
            raise AssertionError(f'{self.operation} was not released by the test')
        if self.fail:
            raise CommitRejected(self.operation)


class CommitGate:
    def __init__(self):
        self._next = None
        self._lock = Lock()

    def arm(self, operation, *, pause=False, fail=False):
        boundary = CommitBoundary(operation, pause, fail)
        with self._lock:
            if self._next is not None:
                raise AssertionError('the previous commit boundary has not been reached')
            self._next = boundary
        return boundary

    def __call__(self, operation):
        with self._lock:
            boundary = self._next
            if boundary is None or operation != boundary.operation:
                return
            self._next = None
        boundary.arrive()


class StationCase(unittest.TestCase):
    capacity = 2

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / 'station.sqlite3'
        self.gate = CommitGate()
        self.store = StationStore(self.db_path, before_commit=self.gate)
        self.addCleanup(self.store.close)
        self.store.initialize()
        self.bridge = AcquisitionBridge(self.store, self.capacity)
        self.admission = AdmissionService(self.store)
        self.dispatch = ReadingDispatch(self.admission)
        self.issuer = ReportIssuer(self.store)

    def open_shift(self, shift_id='day', probe_id='dust-1', multiplier='1/2', offset=1, limit=3):
        self.bridge.open(shift_id, probe_id, multiplier, offset, limit)
        return self.bridge.session(shift_id)

    @staticmethod
    def complete(session, count):
        return session.finish(session.start(), count)

    def sign(self, shift_id, counts):
        session = self.bridge.session(shift_id)
        for count in counts:
            raw = self.complete(session, count)
            self.dispatch.deliver(session, raw.pulse)
        session.stop()
        return self.issuer.issue(shift_id)

    def observe(self, statement, parameters=()):
        with StationStore(self.db_path) as observer, observer.snapshot() as connection:
            return tuple(tuple(row) for row in connection.execute(statement, parameters))

    def take_source_offline(self):
        self.bridge = None
        self.store.close()

    def reopen(self):
        store = StationStore(self.db_path)
        self.addCleanup(store.close)
        return store, ReportLookup(store)
