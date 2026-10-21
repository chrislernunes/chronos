"""The reference-time convention used to compare tagged events.

This is a software convention. It is not a universal absolute time.

Chosen reference
----------------
* Coordinate system: geocentric.
* Time coordinate: Terrestrial Time (TT), IAU.
* Unit: the SI second on the defining rate of TT.
* Epoch: J2000.0 = 2000-01-01T12:00:00 TT = JD 2451545.0.
* Stored representation: integer TT nanoseconds after 1972-01-01T00:00:00 TT.
* Relation to TAI: TT = TAI + 32.184 s exactly, for the same event.
* Relation to UTC: the bundled IERS leap-second table, 1972-01-01 until expiry.
* Relation to UT1: linear interpolation of the bundled Bulletin A snapshot.
* Relation to Mars mean solar time: Mars24, which is defined as a function of TT.
* Relativistic reductions that are implemented: constant-velocity special
  relativity; stationary Schwarzschild rate; weak-field metric rate inside a
  stated domain.
* Not implemented: TDB/TCB, proper time on Mars reduced to TT, spacecraft
  navigation along an ephemeris.

Two events may be subtracted in TT. The difference is a coordinate interval.
It is a proper-time interval only if a reduction that says so was applied, and
only under that reduction's assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass

from chronos.core import Duration, TtInstant, UnsupportedTransformation


@dataclass(frozen=True)
class ReferenceEvent:
    """An event already reduced to TT, or explicitly only a TT coordinate tag."""

    tt: TtInstant
    body: str
    reduction: str
    label: str = ""

    def __post_init__(self) -> None:
        allowed = {"coordinate-tt", "identity-tai-tt"}
        if self.reduction not in allowed:
            raise UnsupportedTransformation(
                f"reduction {self.reduction!r} is not an implemented path to TT. "
                "Supported tags are 'coordinate-tt' (the event is defined in TT) "
                "and 'identity-tai-tt' (the event was converted from TAI by the "
                "exact 32.184 s offset). A Mars-surface proper time or a "
                "spacecraft worldline is not accepted under another name."
            )
        if self.body not in {"earth", "mars", "spacecraft", "coordinate"}:
            raise UnsupportedTransformation(
                "body must be earth, mars, spacecraft, or coordinate. "
                "The body label does not imply a relativistic reduction."
            )


def coordinate_difference(later: ReferenceEvent, earlier: ReferenceEvent) -> Duration:
    """TT coordinate interval. Not automatically a proper-time interval."""

    return Duration(later.tt.nanoseconds - earlier.tt.nanoseconds)


def describe_reference() -> dict[str, object]:
    return {
        "name": "Chronos TT reference",
        "coordinate_system": "geocentric",
        "time_coordinate": "TT",
        "unit": "SI second",
        "epoch": "J2000.0 = 2000-01-01T12:00:00 TT = JD 2451545.0",
        "storage": "integer nanoseconds of TT since 1972-01-01T00:00:00 TT",
        "tai_relation": "TT = TAI + 32.184 s exactly",
        "utc_relation": "IERS leap-seconds.list, 1972-01-01Z until 2027-06-28Z",
        "ut1_relation": "bundled USNO finals.daily snapshot, linear daily interpolation",
        "mars_relation": "NASA GISS Mars24 mean solar convention, a function of TT",
        "implemented_relativistic_reductions": [
            "special_relativistic_constant_velocity",
            "schwarzschild_stationary",
            "weak_field_metric_sqrt",
        ],
        "unsupported": [
            "TDB",
            "TCB",
            "mars_surface_proper_time_to_tt",
            "spacecraft_ephemeris_proper_time",
            "pre-1972 UTC",
        ],
    }
