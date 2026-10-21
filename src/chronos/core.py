"""Canonical durations and continuous time-scale instants.

The canonical elapsed-time representation is an integer number of SI
nanoseconds (Python ``int``, unbounded). One nanosecond is the resolution of
ordinary arithmetic in this package. It is not a claim that physical clocks
or the adopted models are accurate to a nanosecond.

Unix timestamps are not used. They are leap-second-ignorant counts of UTC
seconds and cannot represent 23:59:60.

Origins
-------
* ``TaiInstant.nanoseconds`` counts SI nanoseconds of TAI after
  1972-01-01T00:00:00 TAI.
* ``TtInstant.nanoseconds`` counts SI nanoseconds of TT after
  1972-01-01T00:00:00 TT.

Those origins are not the same event. TT is defined to be ahead of TAI by
32.184 s exactly (IAU), so for one event the TT count is the TAI count plus
32_184_000_000. The offset is an integer number of nanoseconds because
32.184 s = 32.184 × 10⁹ ns exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


TT_MINUS_TAI_NANOSECONDS = 32_184_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
SECONDS_PER_DAY = 86_400

# IAU. J2000.0 is 2000-01-01 12:00:00 TT = JD 2451545.0.
J2000_JD = Decimal("2451545.0")


class ChronosError(Exception):
    """Base class for expected scientific or input failures."""


class InvalidInput(ChronosError):
    """The request is dimensionally or physically invalid."""


class InvalidSpeed(InvalidInput):
    """A speed is negative or not strictly below c."""


class UnsupportedTransformation(ChronosError):
    """The transformation is named and deliberately not evaluated."""


class DataCoverageError(ChronosError):
    """Required reference data does not cover the requested instant."""


@dataclass(frozen=True, order=True)
class Duration:
    """A signed elapsed SI interval. Not attached to a time scale.

    Attributes
    ----------
    nanoseconds:
        Signed SI nanoseconds. Positive means later minus earlier.
    """

    nanoseconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.nanoseconds, int) or isinstance(self.nanoseconds, bool):
            raise InvalidInput("Duration.nanoseconds must be an int")

    @classmethod
    def from_seconds(cls, seconds: Decimal | int) -> Duration:
        from chronos.precision import nanoseconds_from_seconds

        return cls(nanoseconds_from_seconds(Decimal(seconds)))

    def seconds(self) -> Decimal:
        return Decimal(self.nanoseconds) / Decimal(NANOSECONDS_PER_SECOND)

    def __add__(self, other: Duration) -> Duration:
        if not isinstance(other, Duration):
            return NotImplemented
        return Duration(self.nanoseconds + other.nanoseconds)

    def __sub__(self, other: Duration) -> Duration:
        if not isinstance(other, Duration):
            return NotImplemented
        return Duration(self.nanoseconds - other.nanoseconds)

    def __neg__(self) -> Duration:
        return Duration(-self.nanoseconds)


@dataclass(frozen=True, order=True)
class TaiInstant:
    """An event's TAI reading as SI nanoseconds after 1972-01-01T00:00:00 TAI."""

    nanoseconds: int
    scale: str = "TAI"

    def __post_init__(self) -> None:
        if not isinstance(self.nanoseconds, int) or isinstance(self.nanoseconds, bool):
            raise InvalidInput("TaiInstant.nanoseconds must be an int")
        if self.scale != "TAI":
            raise InvalidInput("TaiInstant.scale is fixed as TAI")

    def add(self, duration: Duration) -> TaiInstant:
        return TaiInstant(self.nanoseconds + duration.nanoseconds)


@dataclass(frozen=True, order=True)
class TtInstant:
    """An event's TT reading as SI nanoseconds after 1972-01-01T00:00:00 TT.

    TT is a geocentric coordinate time. A ``TtInstant`` is not a proper-time
    reading of a clock on Mars or on a spacecraft.
    """

    nanoseconds: int
    scale: str = "TT"

    def __post_init__(self) -> None:
        if not isinstance(self.nanoseconds, int) or isinstance(self.nanoseconds, bool):
            raise InvalidInput("TtInstant.nanoseconds must be an int")
        if self.scale != "TT":
            raise InvalidInput("TtInstant.scale is fixed as TT")

    def add(self, duration: Duration) -> TtInstant:
        return TtInstant(self.nanoseconds + duration.nanoseconds)


def tai_to_tt(tai: TaiInstant) -> TtInstant:
    """Map one event from TAI to TT. TT = TAI + 32.184 s exactly."""

    return TtInstant(tai.nanoseconds + TT_MINUS_TAI_NANOSECONDS)


def tt_to_tai(tt: TtInstant) -> TaiInstant:
    """Map one event from TT to TAI. TAI = TT − 32.184 s exactly."""

    return TaiInstant(tt.nanoseconds - TT_MINUS_TAI_NANOSECONDS)


def tt_nanoseconds_at_j2000() -> int:
    """TT nanoseconds of J2000.0 counted from 1972-01-01T00:00:00 TT.

    1972-01-01 to 2000-01-01 is 10 227 SI days of TT (TT has no leap seconds),
    plus 12 h to noon. The day count is the proleptic Gregorian interval and
    is checked in tests against ``datetime.date``.
    """

    from chronos.earth import days_between

    days = days_between(1972, 1, 1, 2000, 1, 1)
    seconds = days * SECONDS_PER_DAY + 12 * 3600
    return seconds * NANOSECONDS_PER_SECOND


def julian_date_tt(tt: TtInstant) -> Decimal:
    """Julian Date of a TT instant.

    Anchor: J2000.0 = JD 2451545.0 = 2000-01-01T12:00:00 TT (IAU).
    The day fraction uses 86 400 SI seconds exactly. TT has no leap seconds.
    """

    delta_ns = Decimal(tt.nanoseconds - tt_nanoseconds_at_j2000())
    day_ns = Decimal(SECONDS_PER_DAY * NANOSECONDS_PER_SECOND)
    return J2000_JD + delta_ns / day_ns
