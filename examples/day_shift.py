import json
from pathlib import Path
from tempfile import TemporaryDirectory

from station.acquisition.dispatch import ReadingDispatch
from station.acquisition.queue import QueueFullError
from station.acquisition.session import AcquisitionBridge
from station.intake.admit import AdmissionService
from station.intake.store import StationStore
from station.report.issue import ReportIssuer
from station.review.lookup import ReportLookup


def main() -> None:
    shift_id, probe_id = 'day', 'dust-1'
    multiplier, offset, limit = '1/2', 1, 3
    counts = (4, 5)
    capacity = 1
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'station.sqlite3'
        with StationStore(path) as store:
            store.initialize()
            bridge = AcquisitionBridge(store, capacity)
            bridge.open(shift_id, probe_id, multiplier, offset, limit)
            session = bridge.session(shift_id)
            dispatch = ReadingDispatch(AdmissionService(store))
            first_raw = session.finish(session.start(), counts[0])
            try:
                session.start()
            except QueueFullError:
                pass
            else:
                raise AssertionError('expected a full-queue pause')
            first = dispatch.deliver(session, first_raw.pulse)
            second_raw = session.finish(session.start(), counts[1])
            second = dispatch.deliver(session, second_raw.pulse)
            session.stop()
            issued = ReportIssuer(store).issue(shift_id)
        del bridge, session, dispatch
        with StationStore(path) as reopened:
            collected = ReportLookup(reopened).read(issued.report_id)

    expected = {'concentrations': ['3', '7/2'], 'exceeded': [False, True]}
    actual = {
        'concentrations': [str(first.concentration), str(second.concentration)],
        'exceeded': [first.exceeded, second.exceeded],
    }
    downstream_expected = {
        'pulses': [1, 2], 'raw_counts': [4, 5], 'total': '13/2',
        'exceeded_pulses': [2], 'same_report': True,
    }
    downstream_actual = {
        'pulses': [item.pulse for item in collected.pulses],
        'raw_counts': [item.raw_count for item in collected.pulses],
        'total': str(collected.recomputed.total),
        'exceeded_pulses': list(collected.recomputed.exceeded_pulses),
        'same_report': collected.report == issued,
    }
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError((actual, downstream_actual))
    print(f'Shift {shift_id}, report {issued.report_id}, total {collected.recomputed.total} {collected.recomputed.unit}')
    scenario = {
        'case_id': 'v7',
        'input': {'shift': shift_id, 'probe': probe_id, 'capacity': capacity,
                  'raw_counts': counts, 'multiplier': multiplier, 'offset': offset, 'limit': limit},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['station/acquisition/session.py', 'station/intake/conversion.py',
                       'station/report/issue.py', 'station/review/lookup.py'],
        'oracle': 'Manual arithmetic: 4/2+1=3, 5/2+1=7/2, 3+7/2=13/2. Only 7/2 is above 3.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
