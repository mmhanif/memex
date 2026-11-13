"""The injectable clock (SPEC §16.3). Dates and times are local to the machine (§4.2)."""

import datetime as dt
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def today(self) -> dt.date: ...

    def now(self) -> dt.datetime: ...


class SystemClock:
    def today(self) -> dt.date:
        return dt.date.today()

    def now(self) -> dt.datetime:
        return dt.datetime.now()


@dataclass(frozen=True)
class FixedClock:
    """A clock stuck on one day (and, if given, one moment of it), for tests."""

    date: dt.date
    moment: dt.datetime | None = None

    def today(self) -> dt.date:
        return self.date

    def now(self) -> dt.datetime:
        return self.moment or dt.datetime.combine(self.date, dt.time())
