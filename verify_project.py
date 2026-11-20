"""Regression suite plus the joint overrun walkthrough, for the runtime manifest."""

from examples.demo import main as run_demo
from check_project import main as run_tests


def main() -> int:
    status = run_tests()
    if status != 0:
        return status
    run_demo()
    print('VERIFY result=PASS (tests and overrun demo)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
