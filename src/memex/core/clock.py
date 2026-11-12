"""The injectable clock (SPEC §16.3). Dates are local to the machine (§4.2)."""

import datetime as dt
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def today(self) -> dt.date: ...


class SystemClock:
    def today(self) -> dt.date:
        return dt.date.today()


@dataclass(frozen=True)
class FixedClock:
    """A clock stuck on one day, for tests."""

    date: dt.date

    def today(self) -> dt.date:
        return self.date
