"""Earth time scales: UTC leap seconds, TAI, and a bundled UT1 snapshot.

UTC is a calendar representation. It is not stored as a fixed offset from TAI.
A positive leap second is the distinct label ``23:59:60`` on the UTC day that
ends at a step of ``TAI−UTC``.

Pre-1972 UTC (rate offsets and fractional steps) is not implemented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib.resources import files
from typing import Iterable

from chronos.core import (
    NANOSECONDS_PER_SECOND,
    SECONDS_PER_DAY,
    DataCoverageError,
    Duration,
    InvalidInput,
    TaiInstant,
    TtInstant,
    tai_to_tt,
    tt_to_tai,
)


class InvalidLeapSecond(InvalidInput):
    """``second == 60`` was requested where no positive leap second exists."""


class LeapTableExpired(DataCoverageError):
    """The bundled IERS leap-second file does not cover this UTC instant."""


@dataclass(frozen=True, order=True)
class UtcTimestamp:
    """A UTC calendar timestamp. ``second`` may be 60 only on a leap second.

    This type has no time zone. Values are UTC, never a host local zone.
    ``nanosecond`` is the fraction of the labeled UTC second, in ``[0, 10⁹)``.
    """

    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    nanosecond: int = 0

    def __post_init__(self) -> None:
        if not _valid_civil_date(self.year, self.month, self.day):
            raise InvalidInput(f"invalid Gregorian date {self.year:04d}-{self.month:02d}-{self.day:02d}")
        if not (0 <= self.hour <= 23 and 0 <= self.minute <= 59):
            raise InvalidInput("hour or minute out of range")
        if not (0 <= self.second <= 60):
            raise InvalidInput("UTC second must be in 0..60")
        if not (0 <= self.nanosecond < NANOSECONDS_PER_SECOND):
            raise InvalidInput("nanosecond must be in 0..999_999_999")
        if isinstance(self.nanosecond, bool) or not isinstance(self.nanosecond, int):
            raise InvalidInput("nanosecond must be an int")

    def format(self) -> str:
        return (
            f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
            f"T{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
            f".{self.nanosecond:09d}Z"
        )


@dataclass(frozen=True)
class LeapSecondTable:
    """Step function ``TAI−UTC`` from the vendored IERS list."""

    entries: tuple[tuple[UtcTimestamp, int], ...]
    expires: UtcTimestamp
    metadata: dict

    def offset_at(self, utc: UtcTimestamp, *, allow_expired: bool = False) -> int:
        """Seconds to add to UTC to get TAI, away from a leap-second label.

        During the leap-second label itself, callers must pass the previous
        day's offset via :meth:`offset_during_leap_label`.
        """

        self._require_coverage(utc, allow_expired=allow_expired)
        return self._offset_in_force(utc)

    def offset_during_leap_label(self, utc: UtcTimestamp, *, allow_expired: bool = False) -> int:
        if not (utc.hour == 23 and utc.minute == 59 and utc.second == 60):
            raise InvalidInput("offset_during_leap_label requires 23:59:60")
        probe = UtcTimestamp(utc.year, utc.month, utc.day, 23, 59, 59, 0)
        return self.offset_at(probe, allow_expired=allow_expired)

    def is_positive_leap_label(self, utc: UtcTimestamp, *, allow_expired: bool = False) -> bool:
        if not (utc.hour == 23 and utc.minute == 59 and utc.second == 60):
            return False
        old = self.offset_during_leap_label(utc, allow_expired=allow_expired)
        nxt = _next_civil_day(utc.year, utc.month, utc.day)
        midnight = UtcTimestamp(nxt[0], nxt[1], nxt[2], 0, 0, 0, 0)
        try:
            new = self.offset_at(midnight, allow_expired=allow_expired)
        except LeapTableExpired:
            return False
        return new == old + 1

    def _require_coverage(self, utc: UtcTimestamp, *, allow_expired: bool) -> None:
        if _cmp_utc(utc, self.entries[0][0]) < 0:
            raise DataCoverageError(
                "UTC before 1972-01-01 is not implemented. "
                "From 1961 to 1972, UTC used frequency offsets and 0.1 s steps, "
                "not the integer leap-second table."
            )
        if _cmp_utc(utc, self.expires) >= 0 and not allow_expired:
            raise LeapTableExpired(
                "Bundled IERS leap-seconds.list expires at "
                f"{self.expires.format()}. No TAI−UTC value is published by this "
                "snapshot at or after that instant. Pass allow_expired=True only "
                "to extrapolate the last announced offset, and label the result "
                "as an extrapolation."
            )

    def _offset_in_force(self, utc: UtcTimestamp) -> int:
        chosen = None
        for effective, offset in self.entries:
            if _cmp_utc(effective, utc) <= 0:
                chosen = offset
            else:
                break
        if chosen is None:
            raise DataCoverageError("UTC instant precedes the leap-second table")
        return chosen


@dataclass(frozen=True)
class EopRow:
    """One daily 0h UTC Earth-orientation sample from IERS Bulletin A."""

    year: int
    month: int
    day: int
    mjd: Decimal
    ut1_minus_utc: Decimal
    ut1_minus_utc_sigma: Decimal
    lod_milliseconds: Decimal | None
    flag: str  # "I" observed/rapid, "P" prediction

    @property
    def utc_midnight(self) -> UtcTimestamp:
        return UtcTimestamp(self.year, self.month, self.day, 0, 0, 0, 0)


@dataclass(frozen=True)
class Ut1Correction:
    """Interpolated UT1−UTC. Not an operational IERS Lagrange reduction."""

    ut1_minus_utc_seconds: Decimal
    formal_sigma_seconds: Decimal
    method: str
    left_flag: str
    right_flag: str
    contains_prediction: bool
    snapshot: str


def load_leap_second_table() -> LeapSecondTable:
    raw = json.loads(files("chronos").joinpath("data/leap_seconds.json").read_text())
    entries = []
    for row in raw["entries"]:
        entries.append((parse_utc(row["effective_utc"]), int(row["tai_minus_utc"])))
    expires = parse_utc(raw["expires_utc"])
    return LeapSecondTable(tuple(entries), expires, {k: v for k, v in raw.items() if k != "entries"})


def load_eop_rows() -> tuple[EopRow, ...]:
    text = files("chronos").joinpath("data/finals.daily.txt").read_text()
    return tuple(parse_finals_daily(text))


def parse_finals_daily(text: str) -> list[EopRow]:
    """Parse USNO/IERS ``finals.daily`` fixed-width Bulletin A records.

    Column layout follows the USNO ser7 ``readme.finals`` description and was
    checked against the bundled file (187-character records):

    * columns 1–2 year (add 2000; all bundled MJDs are after 51544)
    * columns 3–4 month, 5–6 day
    * columns 8–15 MJD
    * column 58 flag for UT1−UTC (``I`` or ``P``)
    * columns 59–68 UT1−UTC in seconds
    * columns 69–78 formal error in seconds
    * columns 80–86 LOD excess in milliseconds (blank on some predictions)
    """

    rows: list[EopRow] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if len(line) < 78:
            continue
        try:
            year = 2000 + int(line[0:2])
            month = int(line[2:4])
            day = int(line[4:6])
            mjd = Decimal(line[7:15].strip())
            flag = line[57]
            ut1 = Decimal(line[58:68].strip())
            sigma = Decimal(line[68:78].strip())
        except (ValueError, IndexError) as exc:
            raise InvalidInput(f"unreadable finals.daily line {line_number}") from exc
        if flag not in {"I", "P"}:
            raise InvalidInput(f"unexpected UT1 flag {flag!r} on line {line_number}")
        lod_txt = line[79:86].strip() if len(line) >= 86 else ""
        lod = Decimal(lod_txt) if lod_txt else None
        rows.append(
            EopRow(
                year=year,
                month=month,
                day=day,
                mjd=mjd,
                ut1_minus_utc=ut1,
                ut1_minus_utc_sigma=sigma,
                lod_milliseconds=lod,
                flag=flag,
            )
        )
    if not rows:
        raise InvalidInput("finals.daily snapshot contained no rows")
    return rows


def parse_utc(text: str) -> UtcTimestamp:
    """Parse ``YYYY-MM-DDThh:mm:ss[.fffffffff]Z``.

    A numeric zone offset is rejected. Local time is not a scientific input.
    """

    if not isinstance(text, str) or not text.endswith("Z"):
        raise InvalidInput(
            "UTC timestamps must end with Z. Numeric offsets and host-local "
            "times are rejected; convert to UTC before calling Chronos."
        )
    body = text[:-1]
    if "T" not in body:
        raise InvalidInput("UTC timestamp must contain a T separator")
    date_part, time_part = body.split("T", 1)
    try:
        year_s, month_s, day_s = date_part.split("-")
        if "." in time_part:
            hms, frac = time_part.split(".", 1)
            if not frac.isdigit() or not (1 <= len(frac) <= 9):
                raise ValueError
            nanosecond = int(frac.ljust(9, "0"))
        else:
            hms = time_part
            nanosecond = 0
        hour_s, minute_s, second_s = hms.split(":")
        stamp = UtcTimestamp(
            int(year_s),
            int(month_s),
            int(day_s),
            int(hour_s),
            int(minute_s),
            int(second_s),
            nanosecond,
        )
    except (ValueError, InvalidInput) as exc:
        raise InvalidInput(
            "UTC timestamp must look like 2017-01-01T00:00:00Z "
            "or 2016-12-31T23:59:60.000000000Z"
        ) from exc
    return stamp


def utc_to_tai(utc: UtcTimestamp, *, allow_expired: bool = False, table: LeapSecondTable | None = None) -> TaiInstant:
    """Convert a UTC label to TAI.

    ``TAI nanoseconds since 1972-01-01T00:00:00 TAI`` equals
    ``posix_like_seconds_since_1972-01-01 UTC + (TAI−UTC)``, in nanoseconds,
    where ``posix_like`` counts calendar days as 86 400 s and allows the
    label second 60 to land on the next POSIX midnight. The leap-second
    label uses the pre-leap offset, so it occupies the SI second immediately
    before the following UTC midnight. See tests for the 2016-12-31 step.
    """

    table = table or load_leap_second_table()
    if utc.second == 60:
        if not table.is_positive_leap_label(utc, allow_expired=allow_expired):
            raise InvalidLeapSecond(
                f"{utc.format()} is not a positive leap second in the bundled IERS table"
            )
        offset = table.offset_during_leap_label(utc, allow_expired=allow_expired)
    else:
        offset = table.offset_at(utc, allow_expired=allow_expired)
    posix_like = _posix_like_seconds(utc)
    tai_seconds = posix_like + offset
    return TaiInstant(tai_seconds * NANOSECONDS_PER_SECOND + utc.nanosecond)


def tai_to_utc(tai: TaiInstant, *, allow_expired: bool = False, table: LeapSecondTable | None = None) -> UtcTimestamp:
    """Convert TAI to a UTC label, including ``23:59:60`` when one exists."""

    table = table or load_leap_second_table()
    if tai.nanoseconds < 10 * NANOSECONDS_PER_SECOND:
        raise DataCoverageError(
            "TAI instants before 1972-01-01T00:00:10 TAI (the UTC epoch of the "
            "leap-second system) are outside the implemented UTC mapping."
        )
    tai_seconds, nanosecond = divmod(tai.nanoseconds, NANOSECONDS_PER_SECOND)
    boundaries = _tai_boundaries(table)
    index = _largest_index_at_most(boundaries, tai_seconds)
    offset = table.entries[index][1]
    if index + 1 < len(boundaries) and tai_seconds == boundaries[index + 1] - 1:
        next_offset = table.entries[index + 1][1]
        if next_offset == offset + 1:
            year, month, day = _previous_civil_day(*_civil_from_effective(table.entries[index + 1][0]))
            stamp = UtcTimestamp(year, month, day, 23, 59, 60, nanosecond)
            _check_expiry(stamp, table, allow_expired)
            return stamp
        if next_offset < offset:
            raise UnsupportedNegativeLeap(
                "A negative leap second would skip a UTC label. None has been "
                "announced; this snapshot does not implement one."
            )
    posix_like = tai_seconds - offset
    year, month, day, hour, minute, second = _utc_from_posix_like(posix_like)
    stamp = UtcTimestamp(year, month, day, hour, minute, second, nanosecond)
    _check_expiry(stamp, table, allow_expired)
    return stamp


class UnsupportedNegativeLeap(DataCoverageError):
    pass


def utc_to_tt(utc: UtcTimestamp, **kwargs: object) -> TtInstant:
    return tai_to_tt(utc_to_tai(utc, **kwargs))  # type: ignore[arg-type]


def tt_to_utc(tt: TtInstant, **kwargs: object) -> UtcTimestamp:
    return tai_to_utc(tt_to_tai(tt), **kwargs)  # type: ignore[arg-type]


def add_duration_utc(utc: UtcTimestamp, duration: Duration, **kwargs: object) -> UtcTimestamp:
    """Advance a UTC label by an SI duration, through TAI.

    This is the only supported way to add time to UTC. Adding 86 400 to the
    clock fields is not one SI day when the interval contains a leap second.
    """

    tai = utc_to_tai(utc, **kwargs)  # type: ignore[arg-type]
    return tai_to_utc(tai.add(duration), **kwargs)  # type: ignore[arg-type]


def tai_minus_utc_seconds(utc: UtcTimestamp, **kwargs: object) -> int:
    """The integer ``TAI−UTC`` in force at ``utc``.

    On a leap-second label the returned value is the pre-leap offset, which is
    the offset that places that label on the SI second before the new offset
    begins.
    """

    table = kwargs.get("table") or load_leap_second_table()
    allow = bool(kwargs.get("allow_expired", False))
    if utc.second == 60:
        return table.offset_during_leap_label(utc, allow_expired=allow)
    return table.offset_at(utc, allow_expired=allow)


def ut1_minus_utc(utc: UtcTimestamp, rows: Iterable[EopRow] | None = None) -> Ut1Correction:
    """Linearly interpolate daily 0h UTC values of UT1−UTC.

    The bundled series is a snapshot of USNO ``finals.daily`` retrieved
    2026-10-21, not a live observation. Linear interpolation between daily
    points is a reproducible offline approximation. It is not the IERS
    conventional multi-point interpolation, and it is not valid across a
    leap second (none falls inside this snapshot).

    The reported sigma is the larger endpoint formal error. That is a
    conservative label, not a propagated uncertainty.
    """

    series = tuple(rows) if rows is not None else load_eop_rows()
    if utc.second == 60:
        raise InvalidInput("UT1 interpolation is not defined on a leap-second label")
    target = _posix_like_seconds(utc)
    indexed = [(_posix_like_seconds(row.utc_midnight), row) for row in series]
    if target < indexed[0][0] or target > indexed[-1][0]:
        raise DataCoverageError(
            "UT1−UTC snapshot covers "
            f"{series[0].utc_midnight.format()} through {series[-1].utc_midnight.format()} "
            "only. No extrapolation is performed. Fetch a newer IERS Bulletin A "
            "product and replace data/finals.daily.txt to extend coverage."
        )
    right = 0
    while right < len(indexed) and indexed[right][0] < target:
        right += 1
    if indexed[right][0] == target:
        row = indexed[right][1]
        return Ut1Correction(
            ut1_minus_utc_seconds=row.ut1_minus_utc,
            formal_sigma_seconds=row.ut1_minus_utc_sigma,
            method="exact daily 0h UTC tabular value; no interpolation",
            left_flag=row.flag,
            right_flag=row.flag,
            contains_prediction=row.flag == "P",
            snapshot="USNO finals.daily retrieved 2026-10-21",
        )
    left = right - 1
    t0, row0 = indexed[left]
    t1, row1 = indexed[right]
    span = Decimal(t1 - t0)
    weight = Decimal(target - t0) / span
    value = row0.ut1_minus_utc + (row1.ut1_minus_utc - row0.ut1_minus_utc) * weight
    sigma = max(row0.ut1_minus_utc_sigma, row1.ut1_minus_utc_sigma)
    return Ut1Correction(
        ut1_minus_utc_seconds=value,
        formal_sigma_seconds=sigma,
        method=(
            "linear interpolation between daily 0h UTC IERS Rapid Service values; "
            "sigma is the larger endpoint formal error, not a full covariance"
        ),
        left_flag=row0.flag,
        right_flag=row1.flag,
        contains_prediction=row0.flag == "P" or row1.flag == "P",
        snapshot="USNO finals.daily retrieved 2026-10-21",
    )


def length_of_day_seconds(lod_milliseconds: Decimal) -> Decimal:
    """SI seconds in the astronomical day: 86 400 s + LOD.

    Bulletin A tabulates LOD as the excess length of the day over 86 400 SI
    seconds, in milliseconds. A UTC day without a leap second is exactly
    86 400 SI seconds by construction. Those are different quantities.
    """

    return Decimal(SECONDS_PER_DAY) + lod_milliseconds / Decimal(1000)


def conventional_utc_day_seconds(contains_positive_leap: bool) -> int:
    """SI seconds in a UTC calendar day: 86 401 if it ends in a leap second."""

    return SECONDS_PER_DAY + (1 if contains_positive_leap else 0)


def days_between(y0: int, m0: int, d0: int, y1: int, m1: int, d1: int) -> int:
    """Proleptic Gregorian whole days from date 0 to date 1."""

    return days_from_civil(y1, m1, d1) - days_from_civil(y0, m0, d0)


def days_from_civil(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01. Howard Hinnant's civil-from-days inverse."""

    y = year
    m = month
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple[int, int, int]:
    """Inverse of :func:`days_from_civil`."""

    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    y += m <= 2
    return y, m, d


def _valid_civil_date(year: int, month: int, day: int) -> bool:
    if not (1 <= month <= 12 and 1 <= day <= 31 and isinstance(year, int)):
        return False
    y, m, d = civil_from_days(days_from_civil(year, month, day))
    return (y, m, d) == (year, month, day)


def _posix_like_seconds(utc: UtcTimestamp) -> int:
    days = days_between(1972, 1, 1, utc.year, utc.month, utc.day)
    return days * SECONDS_PER_DAY + utc.hour * 3600 + utc.minute * 60 + utc.second


def _utc_from_posix_like(seconds: int) -> tuple[int, int, int, int, int, int]:
    if seconds < 0:
        raise DataCoverageError("POSIX-like UTC count precedes 1972-01-01")
    days, rem = divmod(seconds, SECONDS_PER_DAY)
    hour, rem = divmod(rem, 3600)
    minute, second = divmod(rem, 60)
    year, month, day = civil_from_days(days_from_civil(1972, 1, 1) + days)
    return year, month, day, hour, minute, second


def _cmp_utc(a: UtcTimestamp, b: UtcTimestamp) -> int:
    return _posix_like_seconds(a) - _posix_like_seconds(b) or (a.nanosecond - b.nanosecond)


def _next_civil_day(year: int, month: int, day: int) -> tuple[int, int, int]:
    return civil_from_days(days_from_civil(year, month, day) + 1)


def _previous_civil_day(year: int, month: int, day: int) -> tuple[int, int, int]:
    return civil_from_days(days_from_civil(year, month, day) - 1)


def _civil_from_effective(utc: UtcTimestamp) -> tuple[int, int, int]:
    return utc.year, utc.month, utc.day


def _tai_boundaries(table: LeapSecondTable) -> list[int]:
    """TAI second-counts, since 1972-01-01 TAI, of each table effective UTC."""

    return [_posix_like_seconds(utc) + offset for utc, offset in table.entries]


def _largest_index_at_most(bounds: list[int], value: int) -> int:
    index = -1
    for i, bound in enumerate(bounds):
        if bound <= value:
            index = i
        else:
            break
    if index < 0:
        raise DataCoverageError("TAI instant precedes the first leap-second boundary")
    return index


def _check_expiry(stamp: UtcTimestamp, table: LeapSecondTable, allow_expired: bool) -> None:
    if _cmp_utc(stamp, table.expires) >= 0 and not allow_expired:
        raise LeapTableExpired(
            "Converted UTC instant "
            f"{stamp.format()} is at or after leap-second table expiry "
            f"{table.expires.format()}."
        )


def gregorian_oracle_days(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01 using ``datetime.date`` as an independent calendar oracle."""

    return (date(year, month, day) - date(1970, 1, 1)).days
