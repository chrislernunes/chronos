"""Mars mean solar time following the NASA GISS Mars24 recipe.

The mean sol and the Mars Sol Date implemented here are the Allison & McEwen
(2000) convention as updated by the Mars24 algorithm page (NASA GISS, algorithm
dated 2025-01-07). They are functions of Terrestrial Time. They are not the
proper time of a clock on Mars, and they are not an internationally adopted
civil time scale analogous to UTC.

Dividing an SI duration by the mean sol converts units. It does not, by itself,
produce a Martian civil timestamp.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from chronos.core import Duration, TtInstant, julian_date_tt
from chronos.precision import nanoseconds_from_seconds

# Mars24 / AM2000 mean-sol length in Earth days of 86 400 SI seconds.
# Treated as exact as published (11 digits). 1.0274912517 × 86 400 × 10⁹ ns
# is the integer 88 775 244 146 880 ns = 88 775.24414688 s, which rounds to the
# 88 775.244 s figure quoted by NASA GISS technical notes.
MEAN_SOL_EARTH_DAYS = Decimal("1.0274912517")
MEAN_SOL_NANOSECONDS = 10_274_912_517 * 8640

# NASA GISS Mars24 technical notes, quoted: 24h 37m 22.663s.
# A sidereal rotation is not a solar day. The difference is Mars's orbital motion.
SIDEREAL_ROTATION_NANOSECONDS = (24 * 3600 + 37 * 60) * 1_000_000_000 + 22_663_000_000

# MSD phase constants from Mars24 equation C-2.
_MSD_JD_ORIGIN = Decimal("2451549.5")
_MSD_SOL_OFFSET = Decimal("44796.0")
_MSD_PHASE = Decimal("0.0009626")

# Mars24 section B constants (degrees).
_PERTURBERS = (
    (0.0071, 2.2353, 49.409),
    (0.0057, 2.7543, 168.173),
    (0.0039, 1.1177, 191.837),
    (0.0037, 15.7866, 21.736),
    (0.0021, 2.1354, 15.704),
    (0.0020, 2.4694, 95.528),
    (0.0018, 32.8493, 49.095),
)


@dataclass(frozen=True)
class MarsSolarState:
    """Mean and apparent solar quantities on the Mars24 convention.

    Angles are degrees. Clock readings are hours in ``[0, 24)``.
    ``airy_mean_solar_time_hours`` is mean solar time at the Airy-0 meridian
    (Mars24 calls this MST). It is often nicknamed MTC. There is no BIPM-style
    coordinated Martian time behind that nickname.
    """

    julian_date_tt: Decimal
    delta_j2000_days: float
    mars_sol_date: Decimal
    mean_anomaly_deg: float
    fictitious_mean_sun_deg: float
    perturbers_deg: float
    equation_of_center_deg: float
    solar_longitude_deg: float
    equation_of_time_deg: float
    equation_of_time_hours: float
    airy_mean_solar_time_hours: float
    convention: str = "NASA GISS Mars24 algorithm (2025-01-07), Allison & McEwen 2000"


@dataclass(frozen=True)
class LocalMarsTime:
    state: MarsSolarState
    longitude_degrees: float
    longitude_positive: str
    local_mean_solar_time_hours: float
    local_true_solar_time_hours: float


def mean_sol_seconds() -> Decimal:
    return Decimal(MEAN_SOL_NANOSECONDS) / Decimal(1_000_000_000)


def sidereal_rotation_seconds() -> Decimal:
    return Decimal(SIDEREAL_ROTATION_NANOSECONDS) / Decimal(1_000_000_000)


def sols_from_duration(duration: Duration) -> Decimal:
    """Convert an elapsed SI duration into mean sols. Not a civil timestamp."""

    return Decimal(duration.nanoseconds) / Decimal(MEAN_SOL_NANOSECONDS)


def duration_from_sols(sols: Decimal) -> Duration:
    """Inverse of :func:`sols_from_duration`, rounded to the nearest nanosecond."""

    seconds = Decimal(sols) * mean_sol_seconds()
    return Duration(nanoseconds_from_seconds(seconds))


def mars_solar_state(tt: TtInstant) -> MarsSolarState:
    """Evaluate the Mars24 mean-solar recipe at a TT instant.

    Accuracy, as stated by NASA GISS for this analytic series: areocentric
    solar longitude within about 0.008° over ±100 years of J2000, and true
    solar time within a few seconds from the series itself, ignoring
    prime-meridian and topographic error. That is a climate-study recipe, not
    a navigation ephemeris. Apparent solar time additionally needs the
    equation of time; the mean sol alone does not provide it.
    """

    jd = julian_date_tt(tt)
    # The series coefficients were fitted in ordinary double precision.
    dt = float(jd - Decimal("2451545.0"))
    mean_anomaly = _wrap360(19.3871 + 0.52402073 * dt)
    fms = _wrap360(270.3871 + 0.524038496 * dt)
    pbs = 0.0
    for amplitude, period, phase in _PERTURBERS:
        pbs += amplitude * math.cos(math.radians(0.985626 * dt / period + phase))
    eoc = (
        (10.691 + 3.0e-7 * dt) * _sind(mean_anomaly)
        + 0.623 * _sind(2 * mean_anomaly)
        + 0.050 * _sind(3 * mean_anomaly)
        + 0.005 * _sind(4 * mean_anomaly)
        + 0.0005 * _sind(5 * mean_anomaly)
        + pbs
    )
    solar_longitude = _wrap360(fms + eoc)
    eot_deg = (
        2.861 * _sind(2 * solar_longitude)
        - 0.071 * _sind(4 * solar_longitude)
        + 0.002 * _sind(6 * solar_longitude)
        - eoc
    )
    msd = (jd - _MSD_JD_ORIGIN) / MEAN_SOL_EARTH_DAYS + _MSD_SOL_OFFSET - _MSD_PHASE
    mtc = float((msd - msd.to_integral_value(rounding="ROUND_FLOOR")) * 24)
    # Floor of a negative MSD would matter only before the 1873 epoch.
    if msd < 0:
        frac = msd - msd.to_integral_value(rounding="ROUND_FLOOR")
        mtc = float(frac * 24)
    return MarsSolarState(
        julian_date_tt=jd,
        delta_j2000_days=dt,
        mars_sol_date=msd,
        mean_anomaly_deg=mean_anomaly,
        fictitious_mean_sun_deg=fms,
        perturbers_deg=pbs,
        equation_of_center_deg=eoc,
        solar_longitude_deg=solar_longitude,
        equation_of_time_deg=eot_deg,
        equation_of_time_hours=eot_deg / 15.0,
        airy_mean_solar_time_hours=mtc % 24.0,
    )


def local_solar_time(
    tt: TtInstant,
    longitude_degrees: float,
    *,
    positive: str = "east",
) -> LocalMarsTime:
    """Local mean and true solar time.

    ``positive="west"`` is the Mars24 convention:
    ``LMST = MST − Λ_west / 15``.
    ``positive="east"`` uses the opposite sign, which matches the IAU
    planetocentric east-longitude convention. The sign is an argument because
    mixing the two silently produces a wrong local time.
    """

    if positive not in {"east", "west"}:
        raise ValueError("longitude positive direction must be 'east' or 'west'")
    if not math.isfinite(longitude_degrees):
        raise ValueError("longitude must be finite")
    state = mars_solar_state(tt)
    signed = longitude_degrees if positive == "east" else -longitude_degrees
    lmst = (state.airy_mean_solar_time_hours + signed / 15.0) % 24.0
    ltst = (lmst + state.equation_of_time_hours) % 24.0
    return LocalMarsTime(
        state=state,
        longitude_degrees=longitude_degrees,
        longitude_positive=positive,
        local_mean_solar_time_hours=lmst,
        local_true_solar_time_hours=ltst,
    )


def _sind(degrees: float) -> float:
    return math.sin(math.radians(degrees))


def _wrap360(degrees: float) -> float:
    return degrees % 360.0
