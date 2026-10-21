"""Bounded relativistic clock-rate models.

Three calculations are implemented, and they are not interchangeable.

1. Special-relativistic proper time for constant coordinate speed in an
   inertial frame, with no gravitational field::

       dτ = dt √(1 − v²/c²)

2. A clock at rest in the Schwarzschild geometry of a spherical non-rotating
   mass::

       dτ = dt √(1 − r_s/r),   r_s = 2GM/c²

   Here ``t`` is Schwarzschild coordinate time, not TT.

3. A weak-field, slow-motion rate taken from one stated metric, kept as the
   square root rather than an ad hoc product of (1) and (2)::

       Φ = −GM/r
       g_00 = −(1 + 2Φ/c²)
       g_ij = δ_ij (1 − 2Φ/c²)
       (dτ/dt)² = 1 + 2Φ/c² − (1 − 2Φ/c²) v²/c²

None of these is a spacecraft navigation model. Operational comparisons also
need a time ephemeris (TDB/TCB), planetary ephemerides, Shapiro delay, and a
geopotential. Those are exposed as unsupported.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chronos.core import Duration, InvalidInput, InvalidSpeed, UnsupportedTransformation
from chronos.precision import decimal_sqrt, nanoseconds_from_seconds, scale_nanoseconds

# Exact SI definition.
SPEED_OF_LIGHT_M_S = Decimal("299792458")

# IERS Conventions (2010), Petit & Luzum, IERS Technical Note 36, Table 1.1.
EARTH_GM_M3_S2 = Decimal("3.986004418e14")
EARTH_EQUATORIAL_RADIUS_M = Decimal("6378136.6")
EARTH_J2 = Decimal("1.0826359e-3")

# NASA GSFC Mars Fact Sheet values used only inside the spherical model.
# https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html
# GM is quoted there as 4.282837 × 10^4 km³/s². Mean radius 3389.5 km.
MARS_GM_M3_S2 = Decimal("4.282837e13")
MARS_MEAN_RADIUS_M = Decimal("3389500")

# IAU 2012 exact astronomical unit.
AU_METERS = Decimal("149597870700")

# The weak-field derivation assumes |Φ|/c² and v²/c² are small.
# 10⁻⁵ in |Φ|/c² is ~10⁴ times the terrestrial surface potential.
WEAK_FIELD_POTENTIAL_LIMIT = Decimal("1e-5")
WEAK_FIELD_BETA_LIMIT = Decimal("1e-2")


@dataclass(frozen=True)
class Body:
    name: str
    gm_m3_s2: Decimal
    reference_radius_m: Decimal


EARTH = Body("earth", EARTH_GM_M3_S2, EARTH_EQUATORIAL_RADIUS_M)
MARS = Body("mars", MARS_GM_M3_S2, MARS_MEAN_RADIUS_M)
BODIES = {"earth": EARTH, "mars": MARS}


@dataclass(frozen=True)
class ClockRateResult:
    model: str
    proper_over_coordinate: Decimal
    coordinate: Duration
    proper: Duration
    coordinate_time_name: str
    assumptions: tuple[str, ...]
    not_claimed: tuple[str, ...]


def special_relativistic_rate(speed_m_s: Decimal) -> Decimal:
    """``√(1−v²/c²)`` with a stable product form near c. ``v = 0`` returns 1."""

    speed = _as_decimal(speed_m_s, "speed_m_s")
    if speed < 0:
        raise InvalidSpeed("speed must be ≥ 0 m/s; direction is not a signed speed here")
    if speed >= SPEED_OF_LIGHT_M_S:
        raise InvalidSpeed(
            f"speed {speed} m/s is not strictly below c = {SPEED_OF_LIGHT_M_S} m/s. "
            "Superluminal and null coordinate speeds are rejected."
        )
    if speed == 0:
        return Decimal(1)
    beta = speed / SPEED_OF_LIGHT_M_S
    return decimal_sqrt((1 - beta) * (1 + beta))


def special_relativistic_proper_time(coordinate: Duration, speed_m_s: Decimal) -> ClockRateResult:
    rate = special_relativistic_rate(speed_m_s)
    proper = Duration(scale_nanoseconds(coordinate.nanoseconds, rate))
    return ClockRateResult(
        model="special_relativistic_constant_velocity",
        proper_over_coordinate=rate,
        coordinate=coordinate,
        proper=proper,
        coordinate_time_name="inertial coordinate time t in the chosen inertial frame",
        assumptions=(
            "Constant velocity in one inertial frame.",
            "No gravitational field is included.",
            "dτ = dt √((1−β)(1+β)), β = v/c.",
            "The result is rounded to the nearest nanosecond.",
        ),
        not_claimed=(
            "This is not a gravitational redshift.",
            "This is not TDB, TT, or a navigation light-time solution.",
        ),
    )


def schwarzschild_radius_m(gm_m3_s2: Decimal) -> Decimal:
    gm = _as_decimal(gm_m3_s2, "gm")
    if gm <= 0:
        raise InvalidInput("GM must be positive")
    return 2 * gm / (SPEED_OF_LIGHT_M_S ** 2)


def schwarzschild_stationary_rate(radius_m: Decimal, gm_m3_s2: Decimal) -> Decimal:
    """``√(1 − r_s/r)`` for a clock at rest outside a spherical mass."""

    radius = _require_radius(radius_m, gm_m3_s2)
    rs = schwarzschild_radius_m(gm_m3_s2)
    return decimal_sqrt(1 - rs / radius)


def schwarzschild_stationary_proper_time(
    coordinate: Duration,
    radius_m: Decimal,
    gm_m3_s2: Decimal,
    *,
    body_name: str = "specified spherical body",
) -> ClockRateResult:
    rate = schwarzschild_stationary_rate(radius_m, gm_m3_s2)
    proper = Duration(scale_nanoseconds(coordinate.nanoseconds, rate))
    return ClockRateResult(
        model="schwarzschild_stationary",
        proper_over_coordinate=rate,
        coordinate=coordinate,
        proper=proper,
        coordinate_time_name="Schwarzschild coordinate time t (proper time at infinity), not TT",
        assumptions=(
            "Static, spherically symmetric, non-rotating mass.",
            "Clock is at fixed Schwarzschild r (dr = dθ = dφ = 0).",
            "dτ/dt = √(1 − r_s/r), r_s = 2GM/c².",
            f"Body label: {body_name}.",
            "Rounded to the nearest nanosecond.",
        ),
        not_claimed=(
            "Not the rate relative to TT. TT is defined with the geoid potential, not this coordinate.",
            "Earth's J2, rotation, and geoid are omitted. See earth_j2_equatorial_sensitivity().",
            "Not a combined kinematic-plus-gravitational correction.",
        ),
    )


def weak_field_rate(radius_m: Decimal, speed_m_s: Decimal, gm_m3_s2: Decimal) -> Decimal:
    """Positive square root of the stated weak-field metric. See module docstring."""

    radius = _require_radius(radius_m, gm_m3_s2)
    speed = _as_decimal(speed_m_s, "speed_m_s")
    if speed < 0:
        raise InvalidSpeed("speed must be ≥ 0 m/s")
    if speed >= SPEED_OF_LIGHT_M_S:
        raise InvalidSpeed("speed must be strictly below c")
    phi_over_c2 = -( _as_decimal(gm_m3_s2, "gm") / (SPEED_OF_LIGHT_M_S ** 2 * radius) )
    beta2 = (speed / SPEED_OF_LIGHT_M_S) ** 2
    if abs(phi_over_c2) > WEAK_FIELD_POTENTIAL_LIMIT or beta2 > WEAK_FIELD_BETA_LIMIT ** 2:
        raise InvalidInput(
            "Inputs are outside the stated weak-field domain "
            f"(|Φ|/c² ≤ {WEAK_FIELD_POTENTIAL_LIMIT}, v/c ≤ {WEAK_FIELD_BETA_LIMIT}). "
            "Use the special-relativistic model for fast motion without gravity, "
            "or the stationary Schwarzschild model for a clock at rest. "
            "This package does not invent a blended formula outside that domain."
        )
    inside = 1 + 2 * phi_over_c2 - (1 - 2 * phi_over_c2) * beta2
    if inside <= 0:
        raise InvalidInput("weak-field metric factor is not positive for these inputs")
    return decimal_sqrt(inside)


def weak_field_proper_time(
    coordinate: Duration,
    radius_m: Decimal,
    speed_m_s: Decimal,
    gm_m3_s2: Decimal,
    *,
    body_name: str = "specified spherical body",
) -> ClockRateResult:
    rate = weak_field_rate(radius_m, speed_m_s, gm_m3_s2)
    proper = Duration(scale_nanoseconds(coordinate.nanoseconds, rate))
    return ClockRateResult(
        model="weak_field_metric_sqrt",
        proper_over_coordinate=rate,
        coordinate=coordinate,
        proper=proper,
        coordinate_time_name="coordinate time t of the stated weak-field metric, not TT or TDB",
        assumptions=(
            "Metric: g_00 = −(1 + 2Φ/c²), g_ij = δ_ij(1 − 2Φ/c²), Φ = −GM/r.",
            "(dτ/dt)² = 1 + 2Φ/c² − (1 − 2Φ/c²) v²/c².",
            "Constant r and constant coordinate speed. Not an integrated worldline.",
            f"|Φ|/c² ≤ {WEAK_FIELD_POTENTIAL_LIMIT} and v/c ≤ {WEAK_FIELD_BETA_LIMIT} were required.",
            f"Body label: {body_name}.",
            "Rounded to the nearest nanosecond.",
        ),
        not_claimed=(
            "Not a GNSS, geoid, or IAU TT reduction.",
            "Not a solar-system barycentric comparison of Earth and Mars clocks.",
            "Velocity and gravity were not multiplied together as independent fudge factors.",
        ),
    )


def order_c2_expansion(radius_m: Decimal, speed_m_s: Decimal, gm_m3_s2: Decimal) -> Decimal:
    """``1 + Φ/c² − v²/(2c²)``, the expansion of :func:`weak_field_rate` through 1/c².

    Provided so tests can show the size of the dropped terms. Not a second model
    to mix with the square-root result.
    """

    radius = _require_radius(radius_m, gm_m3_s2)
    speed = _as_decimal(speed_m_s, "speed_m_s")
    if speed < 0 or speed >= SPEED_OF_LIGHT_M_S:
        raise InvalidSpeed("speed must be in [0, c)")
    phi_over_c2 = -(_as_decimal(gm_m3_s2, "gm") / (SPEED_OF_LIGHT_M_S ** 2 * radius))
    beta2 = (speed / SPEED_OF_LIGHT_M_S) ** 2
    return 1 + phi_over_c2 - beta2 / 2


def earth_j2_equatorial_sensitivity() -> dict[str, Decimal]:
    """Size of the Earth quadrupole term omitted by the spherical model.

    At the equator, P₂(0) = −1/2, so the J₂ piece of Φ/c² is approximately
    ``−(GM/(c² a)) × (J₂/2)``. Multiplied by 86 400 s this is the omitted
    nanosecond-per-conventional-day scale. It is a sensitivity, not a
    correction that this package applies.
    """

    monopole = EARTH_GM_M3_S2 / (SPEED_OF_LIGHT_M_S ** 2 * EARTH_EQUATORIAL_RADIUS_M)
    j2_piece = monopole * (EARTH_J2 / 2)
    seconds_per_day = j2_piece * Decimal(86400)
    return {
        "monopole_potential_over_c2": monopole,
        "equatorial_j2_potential_over_c2": j2_piece,
        "omitted_seconds_per_86400s_day": seconds_per_day,
        "j2": EARTH_J2,
        "radius_m": EARTH_EQUATORIAL_RADIUS_M,
    }


def vacuum_light_time(distance_m: Decimal) -> Duration:
    """Euclidean distance over c.

    No Shapiro delay, no plasma, no iterative light-time equation, no frame
    transformation. A geometric upper-scale communication delay only.
    """

    distance = _as_decimal(distance_m, "distance_m")
    if distance < 0:
        raise InvalidInput("distance must be ≥ 0 m")
    seconds = distance / SPEED_OF_LIGHT_M_S
    return Duration(nanoseconds_from_seconds(seconds))


def light_time_au(astronomical_units: Decimal) -> Duration:
    au = _as_decimal(astronomical_units, "astronomical_units")
    if au < 0:
        raise InvalidInput("AU distance must be ≥ 0")
    return vacuum_light_time(au * AU_METERS)


def barycentric_dynamical_time(*_args: object, **_kwargs: object) -> None:
    """TDB is a named unsupported transformation.

    IAU 2006 Resolution B3 defines TDB from TCB with L_B, TDB0 and an epoch,
    and TCB−TCG requires the barycentric position and velocity of the geocenter.
    That state comes from a planetary ephemeris. This package does not ship one
    and will not return a two-term sine formula as though it were TDB.
    """

    raise UnsupportedTransformation(
        "TDB/TCB conversion is unsupported. It requires a planetary ephemeris "
        "(for example JPL DE440) for the geocenter's barycentric state, plus the "
        "IAU 2006 rate constants. A two-term Earth-orbit sine is not returned, "
        "because its truncation error is not validated here and would look like "
        "a time-scale transformation."
    )


def _require_radius(radius_m: Decimal, gm: Decimal) -> Decimal:
    radius = _as_decimal(radius_m, "radius_m")
    rs = schwarzschild_radius_m(gm)
    if radius <= rs:
        raise InvalidInput(
            f"radius {radius} m is not outside the Schwarzschild radius {rs} m. "
            "The exterior clock-rate formulas do not apply."
        )
    return radius


def _as_decimal(value: Decimal, name: str) -> Decimal:
    try:
        decimal = Decimal(value)
    except Exception as exc:  # noqa: BLE001 — surface a scientific input error
        raise InvalidInput(f"{name} is not a decimal quantity") from exc
    if not decimal.is_finite():
        raise InvalidInput(f"{name} must be finite")
    return decimal
