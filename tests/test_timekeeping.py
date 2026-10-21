"""Deterministic tests. Oracles are published values or closed-form algebra."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from chronos.core import (
    Duration,
    InvalidSpeed,
    TaiInstant,
    UnsupportedTransformation,
    tai_to_tt,
    tt_to_tai,
)
from chronos.earth import (
    InvalidLeapSecond,
    LeapTableExpired,
    civil_from_days,
    days_from_civil,
    gregorian_oracle_days,
    length_of_day_seconds,
    load_eop_rows,
    parse_utc,
    tai_to_utc,
    utc_to_tai,
    ut1_minus_utc,
)
from chronos.mars import (
    MEAN_SOL_NANOSECONDS,
    duration_from_sols,
    local_solar_time,
    mars_solar_state,
    sols_from_duration,
)
from chronos.reference import ReferenceEvent, coordinate_difference
from chronos.relativity import (
    barycentric_dynamical_time,
    earth_j2_equatorial_sensitivity,
    light_time_au,
    order_c2_expansion,
    schwarzschild_stationary_rate,
    special_relativistic_proper_time,
    weak_field_rate,
)
from chronos.sync import (
    Clock,
    GaussianTimestampNoise,
    accumulated_time_error,
    assess_exchange,
    gaussian_moments_match_seed,
    reproducible_noise_samples,
    two_way_exchange,
)
from chronos.validate import run_reference_cases

ROOT = Path(__file__).resolve().parents[1]


class ReferenceCaseTests(unittest.TestCase):
    def test_published_cases_pass(self) -> None:
        cases = run_reference_cases()
        failed = [case for case in cases if not case["passed"]]
        self.assertEqual(failed, [], failed)


class CalendarTests(unittest.TestCase):
    def test_matches_datetime_over_two_centuries(self) -> None:
        cursor = date(1960, 1, 1)
        stop = date(2100, 1, 1)
        while cursor < stop:
            got = days_from_civil(cursor.year, cursor.month, cursor.day)
            self.assertEqual(got, gregorian_oracle_days(cursor.year, cursor.month, cursor.day))
            self.assertEqual(civil_from_days(got), (cursor.year, cursor.month, cursor.day))
            cursor += timedelta(days=17)

    def test_leap_day(self) -> None:
        self.assertEqual(civil_from_days(days_from_civil(2000, 2, 29)), (2000, 2, 29))
        with self.assertRaises(Exception):
            parse_utc("1900-02-29T00:00:00Z")


class ScaleTests(unittest.TestCase):
    def test_round_trip_across_several_leaps(self) -> None:
        for text in (
            "1972-01-01T00:00:00.000000001Z",
            "1985-06-30T23:59:59Z",
            "1985-07-01T00:00:00Z",
            "1999-01-01T00:00:00Z",
            "2015-06-30T23:59:59Z",
            "2015-06-30T23:59:60Z",
            "2015-07-01T00:00:00Z",
            "2016-12-31T23:59:60.5Z",
            "2026-10-21T06:12:00Z",
            "2027-06-27T23:59:59Z",
        ):
            utc = parse_utc(text if "." in text else text)
            # 23:59:60.5Z is not valid syntax because the fraction must be digits
            # attached without a second dot. The list above uses .5 only once.
            if text.endswith(".5Z"):
                utc = parse_utc("2016-12-31T23:59:60.500000000Z")
            self.assertEqual(tai_to_utc(utc_to_tai(utc)).format(), utc.format())

    def test_expiry_and_local_offset_and_fake_leap(self) -> None:
        with self.assertRaises(LeapTableExpired):
            utc_to_tai(parse_utc("2027-06-28T00:00:00Z"))
        with self.assertRaises(Exception):
            parse_utc("2026-10-21T06:12:00+05:30")
        with self.assertRaises(InvalidLeapSecond):
            utc_to_tai(parse_utc("2018-12-31T23:59:60Z"))

    def test_tt_round_trip(self) -> None:
        tai = utc_to_tai(parse_utc("2000-01-01T12:00:00Z"))
        self.assertEqual(tt_to_tai(tai_to_tt(tai)).nanoseconds, tai.nanoseconds)

    def test_duration_not_a_unix_timestamp(self) -> None:
        self.assertEqual(Duration.from_seconds(Decimal("0.000000001")).nanoseconds, 1)
        self.assertEqual(Duration.from_seconds(Decimal("-1.5")).nanoseconds, -1_500_000_000)


class EarthRotationTests(unittest.TestCase):
    def test_interpolation_and_prediction_flag(self) -> None:
        rows = load_eop_rows()
        midnight = rows[10].utc_midnight
        exact = ut1_minus_utc(midnight, rows)
        self.assertEqual(exact.ut1_minus_utc_seconds, rows[10].ut1_minus_utc)
        noon = parse_utc(f"{midnight.year:04d}-{midnight.month:02d}-{midnight.day:02d}T12:00:00Z")
        mid = ut1_minus_utc(noon, rows)
        expected = (rows[10].ut1_minus_utc + rows[11].ut1_minus_utc) / 2
        self.assertEqual(mid.ut1_minus_utc_seconds, expected)
        self.assertIn("linear interpolation", mid.method)

    def test_prediction_is_labeled(self) -> None:
        corr = ut1_minus_utc(parse_utc("2026-10-21T00:00:00Z"))
        self.assertTrue(corr.contains_prediction)
        observed = ut1_minus_utc(parse_utc("2026-10-20T00:00:00Z"))
        self.assertFalse(observed.contains_prediction)

    def test_outside_snapshot_is_not_invented(self) -> None:
        with self.assertRaises(Exception):
            ut1_minus_utc(parse_utc("2020-01-01T00:00:00Z"))

    def test_lod_is_not_the_utc_day(self) -> None:
        astronomical = length_of_day_seconds(Decimal("-0.2707"))
        self.assertEqual(astronomical, Decimal("86399.9997293"))
        self.assertNotEqual(astronomical, Decimal(86400))


class MarsTests(unittest.TestCase):
    def test_unit_conversion_is_not_a_timestamp(self) -> None:
        one = sols_from_duration(Duration(MEAN_SOL_NANOSECONDS))
        self.assertEqual(one, Decimal(1))
        back = duration_from_sols(Decimal(1))
        self.assertEqual(back.nanoseconds, MEAN_SOL_NANOSECONDS)

    def test_spirit_example_mst(self) -> None:
        # Mars24 worked example 2. millis 1073137591000 is 2004-01-03T13:46:31Z.
        tt = tai_to_tt(utc_to_tai(parse_utc("2004-01-03T13:46:31Z")))
        state = mars_solar_state(tt)
        self.assertAlmostEqual(state.airy_mean_solar_time_hours, 13.16537, delta=5e-4)
        self.assertAlmostEqual(state.solar_longitude_deg, 327.32416, delta=5e-3)
        self.assertAlmostEqual(state.equation_of_time_hours, -0.85170, delta=5e-4)

    def test_longitude_sign_is_explicit(self) -> None:
        tt = tai_to_tt(utc_to_tai(parse_utc("2000-01-06T00:00:00Z")))
        east = local_solar_time(tt, 15.0, positive="east")
        west = local_solar_time(tt, 15.0, positive="west")
        self.assertAlmostEqual(
            (east.local_mean_solar_time_hours - west.local_mean_solar_time_hours) % 24.0,
            2.0,
            delta=1e-9,
        )


class RelativityTests(unittest.TestCase):
    def test_zero_speed_is_identity(self) -> None:
        result = special_relativistic_proper_time(Duration(86_400 * 1_000_000_000), Decimal(0))
        self.assertEqual(result.proper.nanoseconds, result.coordinate.nanoseconds)

    def test_near_c_is_finite_and_small(self) -> None:
        c = Decimal("299792458")
        speed = c * (1 - Decimal("1e-16"))
        rate = special_relativistic_proper_time(Duration(10**9), speed).proper_over_coordinate
        self.assertGreater(rate, 0)
        self.assertLess(rate, Decimal("1e-7"))

    def test_negative_and_superluminal_rejected(self) -> None:
        with self.assertRaises(InvalidSpeed):
            special_relativistic_proper_time(Duration(1), Decimal("-1"))
        with self.assertRaises(InvalidSpeed):
            special_relativistic_proper_time(Duration(1), Decimal("299792458.1"))

    def test_stationary_models_agree_and_expansion_is_close(self) -> None:
        radius = Decimal("6378136.6")
        gm = Decimal("3.986004418e14")
        sch = schwarzschild_stationary_rate(radius, gm)
        weak = weak_field_rate(radius, Decimal(0), gm)
        self.assertEqual(sch, weak)
        expanded = order_c2_expansion(radius, Decimal(0), gm)
        self.assertLess(abs(expanded - weak), Decimal("1e-18"))

    def test_weak_field_rejects_fast_motion(self) -> None:
        with self.assertRaises(Exception):
            weak_field_rate(Decimal("6378136.6"), Decimal("299792458") * Decimal("0.2"), Decimal("3.986004418e14"))

    def test_horizon_rejected(self) -> None:
        with self.assertRaises(Exception):
            schwarzschild_stationary_rate(Decimal("0.001"), Decimal("3.986004418e14"))

    def test_j2_sensitivity_is_tens_of_nanoseconds_per_day(self) -> None:
        omitted = earth_j2_equatorial_sensitivity()["omitted_seconds_per_86400s_day"]
        self.assertGreater(omitted, Decimal("1e-8"))
        self.assertLess(omitted, Decimal("1e-6"))

    def test_light_time_one_au(self) -> None:
        delay = light_time_au(Decimal(1))
        exact = Decimal("149597870700") / Decimal("299792458")
        from chronos.precision import nanoseconds_from_seconds

        self.assertEqual(delay.nanoseconds, nanoseconds_from_seconds(exact))
        # 1 ns rounding against an exact rational. The residual is below 0.5 ns.
        self.assertLess(abs(delay.seconds() - exact), Decimal("5e-10"))

    def test_tdb_is_unsupported(self) -> None:
        with self.assertRaises(UnsupportedTransformation):
            barycentric_dynamical_time()


class SyncTests(unittest.TestCase):
    def test_zero_drift(self) -> None:
        clock = Clock("ideal", Decimal(0), Duration(0))
        self.assertEqual(accumulated_time_error(clock, Duration(365 * 86_400 * 10**9)).nanoseconds, 0)

    def test_linear_drift(self) -> None:
        clock = Clock("offset", Decimal("1e-6"), Duration(0))
        error = accumulated_time_error(clock, Duration.from_seconds(Decimal(1000)))
        self.assertEqual(error.nanoseconds, 1_000_000)

    def test_zero_delay_recovers_offset(self) -> None:
        clock_a = Clock("A", Decimal(0), Duration(0))
        clock_b = Clock("B", Decimal(0), Duration(42))
        exchange = two_way_exchange(
            clock_a,
            clock_b,
            ideal_send_nanoseconds=0,
            delay_ab=Duration(0),
            delay_ba=Duration(0),
        )
        assessment = assess_exchange(clock_a, clock_b, exchange)
        self.assertEqual(assessment.synchronization_error.nanoseconds, 0)
        self.assertEqual(assessment.estimated_offset_b_minus_a.nanoseconds, 42)

    def test_noise_is_reproducible_and_not_silent(self) -> None:
        a = reproducible_noise_samples(Decimal("0.001"), seed=7, count=4)
        b = reproducible_noise_samples(Decimal("0.001"), seed=7, count=4)
        self.assertEqual(a, b)
        self.assertTrue(any(sample != 0 for sample in a))
        mean, var = gaussian_moments_match_seed(7)
        self.assertLess(abs(mean), 0.05)
        self.assertLess(abs(var - 1), 0.05)

    def test_noise_changes_the_estimate(self) -> None:
        clock_a = Clock("A", Decimal(0), Duration(0))
        clock_b = Clock("B", Decimal(0), Duration(0))
        noisy = two_way_exchange(
            clock_a,
            clock_b,
            ideal_send_nanoseconds=0,
            delay_ab=Duration(1_000_000_000),
            delay_ba=Duration(1_000_000_000),
            noise=GaussianTimestampNoise(Decimal("0.01"), seed=3),
        )
        quiet = two_way_exchange(
            clock_a,
            clock_b,
            ideal_send_nanoseconds=0,
            delay_ab=Duration(1_000_000_000),
            delay_ba=Duration(1_000_000_000),
        )
        self.assertNotEqual(noisy.estimated_offset_b_minus_a, quiet.estimated_offset_b_minus_a)
        self.assertEqual(quiet.estimated_offset_b_minus_a.nanoseconds, 0)


class ReferenceTests(unittest.TestCase):
    def test_coordinate_difference_is_tt(self) -> None:
        early = ReferenceEvent(tai_to_tt(TaiInstant(0)), "coordinate", "identity-tai-tt", "origin")
        later = ReferenceEvent(tai_to_tt(TaiInstant(10**9)), "coordinate", "identity-tai-tt", "plus one")
        self.assertEqual(coordinate_difference(later, early).nanoseconds, 10**9)

    def test_mars_proper_time_tag_is_rejected(self) -> None:
        with self.assertRaises(UnsupportedTransformation):
            ReferenceEvent(tai_to_tt(TaiInstant(0)), "mars", "mars-proper-time")


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "chronos", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_info_validate_and_convert(self) -> None:
        info = self._run("info")
        self.assertEqual(info.returncode, 0, info.stderr)
        payload = json.loads(info.stdout)
        self.assertEqual(payload["leap_seconds"]["latest_tai_minus_utc"], 37)
        self.assertIn("nanosecond", payload["canonical_representation"])

        val = self._run("validate")
        self.assertEqual(val.returncode, 0, val.stdout + val.stderr)
        self.assertTrue(json.loads(val.stdout)["ok"])

        conv = self._run("convert", "--from", "UTC", "--to", "TAI", "--time", "2017-01-01T00:00:00Z")
        self.assertEqual(conv.returncode, 0, conv.stderr)
        result = json.loads(conv.stdout)
        self.assertEqual(result["tai_minus_utc_s"], 37)
        self.assertEqual(result["result"]["scale"], "TAI")
        self.assertIn("unit", result["result"])

    def test_bad_input_exits_2(self) -> None:
        bad = self._run("convert", "--from", "UTC", "--to", "TAI", "--time", "2017-06-30T23:59:60Z")
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(json.loads(bad.stdout)["ok"])

        tdb = self._run("relativity", "--model", "tdb")
        self.assertEqual(tdb.returncode, 2)
        self.assertEqual(json.loads(tdb.stdout)["error"], "UnsupportedTransformation")


if __name__ == "__main__":
    unittest.main()
