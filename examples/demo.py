"""Run the original day-shift demo and the overrun delivery demo in one command."""

from examples import day_shift, overload_day


def main() -> None:
    day_shift.main()
    overload_day.main()


if __name__ == '__main__':
    main()
