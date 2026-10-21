"""Published identities used by ``chronos validate``.

Expected numbers are transcribed from IERS and NASA GISS sources, or are
exact algebraic consequences of the stated formulas. They are not copied
from a previous run of this package.
"""

from __future__ import annotations

from decimal import Decimal

from chronos.core import NANOSECONDS_PER_SECOND, Duration, tai_to_tt
from chronos.earth import (
    add_duration_utc,
    days_between,
    load_eop_rows,
    load_leap_second_table,
    parse_utc,
    tai_minus_utc_seconds,
    tai_to_utc,
    utc_to_tai,
    utc_to_tt,
)
from chronos.mars import mars_solar_state, mean_sol_seconds
from chronos.relativity import special_relativistic_rate
from chronos.sync import Clock, assess_exchange, two_way_exchange


def run_reference_cases() -> list[dict[str, object]]:
    checks = (
        _leap_epoch,
        _leap_2017,
        _leap_label_is_one_second,
        _tt_offset,
        _reject_fake_leap,
        _ntp_stamps_match_calendar,
        _mars24_worked_example,
        _mean_sol_rounds_to_nasa_quote,
        _special_relativistic_three_fifths,
        _reject_luminal_speed,
        _sync_asymmetry_bias,
        _eop_snapshot_first_row,
        _gregorian_anchor,
    )
    results = []
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 — one case must not hide the others
            results.append({"name": check.__name__, "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        else:
            results.append({"name": check.__name__, "passed": True, "detail": "ok"})
    return results


def _leap_epoch() -> None:
    utc = parse_utc("1972-01-01T00:00:00Z")
    if tai_minus_utc_seconds(utc) != 10:
        raise AssertionError("TAI−UTC at 1972-01-01 must be 10 s")
    tai = utc_to_tai(utc)
    if tai.nanoseconds != 10 * NANOSECONDS_PER_SECOND:
        raise AssertionError("1972-01-01 UTC is 10 SI seconds after 1972-01-01 TAI")
    if tai_to_utc(tai).format() != utc.format():
        raise AssertionError("TAI/UTC round trip failed at the leap-second epoch")


def _leap_2017() -> None:
    utc = parse_utc("2017-01-01T00:00:00Z")
    if tai_minus_utc_seconds(utc) != 37:
        raise AssertionError("TAI−UTC since 2017-01-01 must be 37 s")


def _leap_label_is_one_second() -> None:
    before = parse_utc("2016-12-31T23:59:59Z")
    leap = add_duration_utc(before, Duration(NANOSECONDS_PER_SECOND))
    after = add_duration_utc(leap, Duration(NANOSECONDS_PER_SECOND))
    if leap.format() != "2016-12-31T23:59:60.000000000Z":
        raise AssertionError(f"expected leap label, got {leap.format()}")
    if after.format() != "2017-01-01T00:00:00.000000000Z":
        raise AssertionError(f"expected midnight after the leap, got {after.format()}")
    if tai_minus_utc_seconds(leap) != 36:
        raise AssertionError("the leap label uses the pre-leap offset 36 s")
    if tai_minus_utc_seconds(after) != 37:
        raise AssertionError("the following midnight uses 37 s")


def _tt_offset() -> None:
    tai = utc_to_tai(parse_utc("2017-01-01T00:00:00Z"))
    tt = tai_to_tt(tai)
    if tt.nanoseconds - tai.nanoseconds != 32_184_000_000:
        raise AssertionError("TT − TAI must be 32.184 s exactly")


def _reject_fake_leap() -> None:
    from chronos.earth import InvalidLeapSecond

    try:
        utc_to_tai(parse_utc("2017-06-30T23:59:60Z"))
    except InvalidLeapSecond:
        return
    raise AssertionError("a non-leap 23:59:60 must be rejected")


def _ntp_stamps_match_calendar() -> None:
    table = load_leap_second_table()
    # NTP seconds are SI seconds since 1900-01-01T00:00:00, ignoring leap smearing.
    # The IERS file's first stamp is the well-known 2 272 060 800 = 1972-01-01.
    days = days_between(1900, 1, 1, 1972, 1, 1)
    if days * 86_400 != 2_272_060_800:
        raise AssertionError("Gregorian day count does not reproduce the 1972 NTP stamp")
    if table.metadata["file_updated_ntp"] != 3_992_312_697:
        raise AssertionError("unexpected leap-second file update stamp")
    expiry_days = days_between(1900, 1, 1, 2027, 6, 28)
    if expiry_days * 86_400 != table.metadata["expires_ntp"]:
        raise AssertionError("expiry date and NTP expiry stamp disagree")


def _mars24_worked_example() -> None:
    # NASA GISS Mars24 worked example: 2000-01-06 00:00:00 UTC.
    # Published: Ls 277.18758°, EOT −0.34585 h, MST 23.99425 h.
    tt = utc_to_tt(parse_utc("2000-01-06T00:00:00Z"))
    state = mars_solar_state(tt)
    _close(state.solar_longitude_deg, 277.18758, 5e-4, "Ls")
    _close(state.equation_of_time_hours, -0.34585, 5e-5, "EOT hours")
    _close(state.airy_mean_solar_time_hours, 23.99425, 5e-4, "MST")
    _close(state.mean_anomaly_deg, 21.74558, 5e-4, "M")


def _mean_sol_rounds_to_nasa_quote() -> None:
    # NASA GISS technical notes quote 24h 39m 35.244s = 88775.244 s.
    quoted = mean_sol_seconds().quantize(Decimal("0.001"))
    if quoted != Decimal("88775.244"):
        raise AssertionError(f"mean sol rounds to {quoted}, not 88775.244 s")


def _special_relativistic_three_fifths() -> None:
    rate = special_relativistic_rate(Decimal("0.6") * Decimal("299792458"))
    if rate != Decimal("0.8"):
        raise AssertionError(f"√(1−0.36) must be exactly 0.8, got {rate}")


def _reject_luminal_speed() -> None:
    from chronos.core import InvalidSpeed

    try:
        special_relativistic_rate(Decimal("299792458"))
    except InvalidSpeed:
        return
    raise AssertionError("v = c must be rejected")


def _sync_asymmetry_bias() -> None:
    clock_a = Clock("A", Decimal(0), Duration(0))
    clock_b = Clock("B", Decimal(0), Duration(5 * NANOSECONDS_PER_SECOND))
    delay_ab = Duration(10 * NANOSECONDS_PER_SECOND)
    delay_ba = Duration(4 * NANOSECONDS_PER_SECOND)
    exchange = two_way_exchange(
        clock_a,
        clock_b,
        ideal_send_nanoseconds=0,
        delay_ab=delay_ab,
        delay_ba=delay_ba,
    )
    assessment = assess_exchange(clock_a, clock_b, exchange)
    # True offset 5 s. Asymmetry 6 s. Bias +3 s. Estimate 8 s.
    if assessment.estimated_offset_b_minus_a.nanoseconds != 8 * NANOSECONDS_PER_SECOND:
        raise AssertionError("symmetric-delay estimate did not pick up half the asymmetry")
    if assessment.synchronization_error.nanoseconds != 3 * NANOSECONDS_PER_SECOND:
        raise AssertionError("synchronization error must equal half the delay asymmetry")


def _eop_snapshot_first_row() -> None:
    rows = load_eop_rows()
    first = rows[0]
    if (first.year, first.month, first.day) != (2026, 7, 23):
        raise AssertionError("bundled finals.daily should start at 2026-07-23")
    if first.ut1_minus_utc != Decimal("0.0093744"):
        raise AssertionError("first UT1−UTC sample does not match the vendored record")
    if first.flag != "I":
        raise AssertionError("first sample should be an IERS rapid value, not a prediction")


def _gregorian_anchor() -> None:
    if days_between(1972, 1, 1, 2000, 1, 1) != 10227:
        raise AssertionError("1972-01-01 to 2000-01-01 must be 10227 days")


def _close(actual: float, expected: float, tol: float, name: str) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(f"{name}: got {actual}, expected {expected} ± {tol}")
