import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from station.acquisition.dispatch import ReadingDispatch
from station.acquisition.session import AcquisitionBridge
from station.intake.admit import AdmissionService
from station.intake.store import StationStore


class RejectedOnce:
    """Deterministic stand-in for a station write rejected at commit time."""

    def __init__(self) -> None:
        self.armed = False

    def __call__(self, operation: str) -> None:
        if self.armed and operation == 'deliver_prefix':
            self.armed = False
            raise RuntimeError('station write deferred')


def _rows(batch: dict) -> list[dict]:
    return [
        row if 'missing' in row else {**row, 'concentration': str(row['concentration'])}
        for row in batch['rows']
    ]


def main() -> None:
    probe_id, multiplier, offset, limit = 'dust-1', '1/2', 1, 3
    capacity = 2
    completed = (4, 5, 6, 7)
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'station.sqlite3'
        with StationStore(path) as store:
            store.initialize()
            bridge = AcquisitionBridge(store, capacity)
            dispatch = ReadingDispatch(AdmissionService(store))

            bridge.open('night', probe_id, multiplier, offset, limit, overrun=True)
            night = bridge.session('night')
            for count in completed:
                night.finish(night.start(), count)
            in_flight = night.start()  # pulse 5 is in flight and must not become a gap
            first = dispatch.deliver_prefix(night)
            if dispatch.deliver_prefix(night) is not None:
                raise AssertionError('an empty prefix produced a batch')
            night.finish(in_flight, 8)  # pulse 5 regains a freed slot after delivery
            tail_gap = dispatch.deliver_prefix(night)
        del bridge, night, in_flight, dispatch

        with StationStore(path) as reopened:
            night_prefix = AdmissionService(reopened).read_prefix('night')

        # A second shift exercises a rejected first delivery and its continuation.
        gate = RejectedOnce()
        with StationStore(path, before_commit=gate) as store:
            store.initialize()
            bridge = AcquisitionBridge(store, capacity)
            dispatch = ReadingDispatch(AdmissionService(store))
            bridge.open('late', probe_id, multiplier, offset, limit, overrun=True)
            late = bridge.session('late')
            for count in completed:
                late.finish(late.start(), count)
            pending = late.start()
            gate.armed = True
            try:
                dispatch.deliver_prefix(late)
            except RuntimeError:
                pass
            else:
                raise AssertionError('the deferred station write was not rejected')
            held_after_reject = len(late.held_readings())
            late.finish(pending, 8)
            retry = dispatch.deliver_prefix(late)
            late.finish(late.start(), 9)
            second = dispatch.deliver_prefix(late)
        del bridge, late, pending, dispatch

        with StationStore(path) as reopened:
            admission = AdmissionService(reopened)
            late_prefix = admission.read_prefix('late')
            fixed = admission.read_batch(retry['batch_id'])
            tail = admission.read_batch(second['batch_id'])

    expected_first = [
        {'pulse': 1, 'raw_count': 4, 'concentration': '3', 'exceeded': False},
        {'pulse': 2, 'raw_count': 5, 'concentration': '7/2', 'exceeded': True},
        {'pulse': 3, 'missing': 'overrun'},
        {'pulse': 4, 'missing': 'overrun'},
    ]
    expected_night_tail = [
        {'pulse': 5, 'raw_count': 8, 'concentration': '5', 'exceeded': True},
    ]
    expected_retry = expected_first + [{'pulse': 5, 'missing': 'overrun'}]
    expected_second = [
        {'pulse': 6, 'raw_count': 9, 'concentration': '11/2', 'exceeded': True},
    ]

    def exact(rows):
        return [row if 'missing' in row else {**row, 'concentration': Fraction(row['concentration'])}
                for row in rows]

    actual = {
        'first': _rows(first),
        'night_tail': _rows(tail_gap),
        'night_prefix': _rows({'rows': night_prefix}),
        'held_after_reject': held_after_reject,
        'retry': _rows(retry),
        'second': _rows(second),
        'late_prefix': _rows({'rows': late_prefix}),
        'night_missing': [row['pulse'] for row in night_prefix if 'missing' in row],
        'fixed_batch_matches': fixed == retry,
        'tail_batch_matches': tail == second,
        'prefix_matches': late_prefix == exact(expected_retry + expected_second),
    }
    expected = {
        'first': expected_first,
        'night_tail': expected_night_tail,
        'night_prefix': expected_first + expected_night_tail,
        'held_after_reject': 2,
        'retry': expected_retry,
        'second': expected_second,
        'late_prefix': expected_retry + expected_second,
        'night_missing': [3, 4],
        'fixed_batch_matches': True,
        'tail_batch_matches': True,
        'prefix_matches': True,
    }
    if actual != expected:
        raise AssertionError((actual, expected))
    print(f'Shift night: batch {first["batch_id"]} pulses 1-4 ends in two tail gaps; '
          f'pulse 5 then regains a slot and rides the next batch')
    print(f'Shift late: batch {retry["batch_id"]} pulses 1-5 after a rejected first attempt, '
          f'batch {second["batch_id"]} pulse 6')
    print(json.dumps({'first': actual['first'], 'retry': actual['retry'],
                      'second': actual['second']}, ensure_ascii=False))
    scenario = {
        'case_id': 'overload-demo',
        'input': {'probe': probe_id, 'capacity': capacity,
                  'completed_counts': list(completed), 'active_count': 8,
                  'next_count': 9, 'multiplier': multiplier,
                  'offset': offset, 'limit': limit},
        'expected': expected,
        'actual': actual,
        'code_paths': ['station/acquisition/session.py', 'station/acquisition/dispatch.py',
                       'station/intake/delivery.py', 'station/intake/admit.py'],
        'oracle': ('Manual arithmetic: 4/2+1=3, 5/2+1=7/2, 9/2+1=11/2. '
                   'Slots keep raw reads 1 and 2; pulses 3 and 4 finish with no slot left. '
                   'After the first batch frees the slots, pulse 5 is retained and rides the '
                   'next batch. The rejected attempt on the other shift leaves both raw reads '
                   'held, keeps the old position, and the retry delivers them unchanged with '
                   'the newly finished pulses as overrun gaps.'),
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
