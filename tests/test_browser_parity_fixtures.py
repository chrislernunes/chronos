"""Keep the shared browser fixtures equal to this Python package."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from chronos.core import NANOSECONDS_PER_SECOND, julian_date_tt, tai_to_tt
from chronos.earth import (
    InvalidLeapSecond,
    LeapTableExpired,
    DataCoverageError,
    parse_utc,
    tai_minus_utc_seconds,
    tai_to_utc,
    ut1_minus_utc,
    utc_to_tai,
)
from chronos.mars import local_solar_time, mars_solar_state
from chronos.relativity import (
    EARTH_EQUATORIAL_RADIUS_M,
    EARTH_GM_M3_S2,
    MARS_GM_M3_S2,
    MARS_MEAN_RADIUS_M,
    schwarzschild_stationary_rate,
    special_relativistic_rate,
    vacuum_light_time,
    weak_field_rate,
)
from chronos.sync import Clock, Duration, assess_exchange, two_way_exchange

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "browser_parity.json"


class BrowserParityFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(FIXTURE.read_text())

    def test_utc_vectors(self) -> None:
        for row in self.data["utc"]:
            stamp = parse_utc(row["input"])
            tai = utc_to_tai(stamp)
            tt = tai_to_tt(tai)
            self.assertEqual(tai_minus_utc_seconds(stamp), row["offset"], row["input"])
            self.assertEqual(str(tai.nanoseconds), row["tai"], row["input"])
            self.assertEqual(str(tt.nanoseconds), row["tt"], row["input"])
            self.assertEqual(tai_to_utc(tai).format(), row["back"], row["input"])
            self.assertEqual(str(julian_date_tt(tt)), row["jd"], row["input"])

    def test_rejections(self) -> None:
        expected = {
            "DataCoverageError": DataCoverageError,
            "LeapTableExpired": LeapTableExpired,
            "InvalidLeapSecond": InvalidLeapSecond,
            "InvalidInput": Exception,
        }
        for row in self.data["rejections"]:
            with self.assertRaises(expected[row["error"]]):
                utc_to_tai(parse_utc(row["input"]))

    def test_ut1_vectors(self) -> None:
        for row in self.data["ut1"]:
            corr = ut1_minus_utc(parse_utc(row["input"]))
            self.assertEqual(str(corr.ut1_minus_utc_seconds), row["seconds"])
            self.assertEqual(str(corr.formal_sigma_seconds), row["sigma"])
            self.assertEqual(corr.contains_prediction, row["prediction"])
        for text in self.data["ut1Rejections"]:
            with self.assertRaises(Exception):
                ut1_minus_utc(parse_utc(text))

    def test_mars_vectors(self) -> None:
        for row in self.data["mars"]:
            tt = tai_to_tt(utc_to_tai(parse_utc(row["input"])))
            state = mars_solar_state(tt)
            local = local_solar_time(tt, row["longitude"], positive=row["positive"])
            self.assertEqual(str(state.julian_date_tt), row["jd"])
            self.assertEqual(str(state.mars_sol_date), row["msd"])
            self.assertEqual(state.airy_mean_solar_time_hours, row["mst"])
            self.assertEqual(state.solar_longitude_deg, row["ls"])
            self.assertEqual(state.equation_of_time_hours, row["eot"])
            self.assertEqual(state.mean_anomaly_deg, row["meanAnomaly"])
            self.assertEqual(local.local_mean_solar_time_hours, row["lmst"])
            self.assertEqual(local.local_true_solar_time_hours, row["ltst"])

    def test_rates_light_time_and_sync(self) -> None:
        c = Decimal("299792458")
        rates = {
            "sr0": special_relativistic_rate(Decimal(0)),
            "sr06": special_relativistic_rate(Decimal("0.6") * c),
            "schEarth": schwarzschild_stationary_rate(EARTH_EQUATORIAL_RADIUS_M, EARTH_GM_M3_S2),
            "weakEarth0": weak_field_rate(EARTH_EQUATORIAL_RADIUS_M, Decimal(0), EARTH_GM_M3_S2),
            "schMars": schwarzschild_stationary_rate(MARS_MEAN_RADIUS_M, MARS_GM_M3_S2),
            "weakMars7800": weak_field_rate(MARS_MEAN_RADIUS_M, Decimal(7800), MARS_GM_M3_S2),
            "weakEarth7800": weak_field_rate(EARTH_EQUATORIAL_RADIUS_M, Decimal(7800), EARTH_GM_M3_S2),
        }
        for name, value in rates.items():
            self.assertEqual(str(value), self.data["rates"][name])
        self.assertEqual(
            str(vacuum_light_time(Decimal("149597870700")).nanoseconds),
            self.data["lightAuNs"],
        )
        clock_a = Clock("A", Decimal(0), Duration(0))
        clock_b = Clock("B", Decimal(0), Duration(5 * NANOSECONDS_PER_SECOND))
        exchange = two_way_exchange(
            clock_a,
            clock_b,
            ideal_send_nanoseconds=0,
            delay_ab=Duration(10 * NANOSECONDS_PER_SECOND),
            delay_ba=Duration(4 * NANOSECONDS_PER_SECOND),
        )
        assessment = assess_exchange(clock_a, clock_b, exchange)
        self.assertEqual(str(assessment.estimated_offset_b_minus_a.nanoseconds), self.data["syncNs"]["estimated"])
        self.assertEqual(str(assessment.synchronization_error.nanoseconds), self.data["syncNs"]["error"])
        self.assertEqual(str(assessment.analytic_asymmetry_bias.nanoseconds), self.data["syncNs"]["bias"])


if __name__ == "__main__":
    unittest.main()
