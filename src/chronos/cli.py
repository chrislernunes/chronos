"""Command line for Chronos.

Every successful numeric result is JSON and names its unit, time scale, and
the assumptions that produced it. Failures exit 2 with a JSON error object.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from typing import Any

from chronos import __version__
from chronos.core import ChronosError, Duration, UnsupportedTransformation
from chronos.earth import (
    load_eop_rows,
    load_leap_second_table,
    parse_utc,
    tai_minus_utc_seconds,
    tai_to_utc,
    utc_to_tai,
    utc_to_tt,
    ut1_minus_utc,
)
from chronos.mars import (
    MEAN_SOL_EARTH_DAYS,
    duration_from_sols,
    local_solar_time,
    mars_solar_state,
    mean_sol_seconds,
    sidereal_rotation_seconds,
    sols_from_duration,
)
from chronos.reference import describe_reference
from chronos.relativity import (
    AU_METERS,
    BODIES,
    SPEED_OF_LIGHT_M_S,
    barycentric_dynamical_time,
    earth_j2_equatorial_sensitivity,
    light_time_au,
    schwarzschild_stationary_proper_time,
    special_relativistic_proper_time,
    vacuum_light_time,
    weak_field_proper_time,
)
from chronos.sync import Clock, accumulated_time_error, assess_exchange, two_way_exchange
from chronos.validate import run_reference_cases


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = args.func(args)
    except ChronosError as exc:
        _emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2
    _emit(payload)
    if getattr(args, "command", None) == "validate" and not payload.get("ok", False):
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronos", description="Interplanetary timekeeping engine")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="Scales, coverage, constants, and non-goals")
    info.set_defaults(func=_cmd_info)

    convert = sub.add_parser("convert", help="Convert one instant or one duration")
    convert.add_argument("--from", dest="source", required=True, choices=["UTC", "TAI", "TT", "SI", "SOL"])
    convert.add_argument("--to", dest="target", required=True)
    convert.add_argument("--time", help="UTC instant, required for UTC input")
    convert.add_argument("--tai-ns", type=int, help="TAI nanoseconds since 1972-01-01T00:00:00 TAI")
    convert.add_argument("--seconds", help="SI seconds when --from SI")
    convert.add_argument("--sols", help="Mean sols when --from SOL")
    convert.add_argument("--longitude-deg", help="Optional Mars longitude for local solar time")
    convert.add_argument("--longitude-positive", choices=["east", "west"], default="east")
    convert.add_argument("--allow-expired", action="store_true")
    convert.set_defaults(func=_cmd_convert)

    rel = sub.add_parser("relativity", help="Bounded proper-time models")
    rel.add_argument("--model", required=True, choices=["sr", "schwarzschild", "weak-field", "tdb"])
    rel.add_argument("--coordinate-seconds", default="1")
    rel.add_argument("--speed-m-s", default="0")
    rel.add_argument("--body", choices=sorted(BODIES), default="earth")
    rel.add_argument("--radius-m")
    rel.add_argument("--distance-m")
    rel.add_argument("--au")
    rel.set_defaults(func=_cmd_relativity)

    sim = sub.add_parser("simulate", help="Frequency accumulation or two-way sync")
    sim_sub = sim.add_subparsers(dest="sim", required=True)
    drift = sim_sub.add_parser("drift")
    drift.add_argument("--y", required=True, help="Dimensionless fractional frequency offset")
    drift.add_argument("--seconds", required=True, help="Ideal elapsed SI seconds")
    drift.set_defaults(func=_cmd_drift)
    sync = sim_sub.add_parser("sync")
    sync.add_argument("--delay-ab-seconds", required=True)
    sync.add_argument("--delay-ba-seconds", required=True)
    sync.add_argument("--offset-b-seconds", default="0")
    sync.add_argument("--y-a", default="0")
    sync.add_argument("--y-b", default="0")
    sync.add_argument("--send-seconds", default="0")
    sync.set_defaults(func=_cmd_sync)

    val = sub.add_parser("validate", help="Check published reference identities")
    val.set_defaults(func=_cmd_validate)
    return parser


def _cmd_info(_args: argparse.Namespace) -> dict[str, Any]:
    table = load_leap_second_table()
    rows = load_eop_rows()
    j2 = earth_j2_equatorial_sensitivity()
    return {
        "ok": True,
        "name": "Chronos",
        "version": __version__,
        "canonical_representation": "signed integer SI nanoseconds",
        "resolution": "1 ns",
        "reference": describe_reference(),
        "leap_seconds": {
            "source": table.metadata["url"],
            "retrieved": table.metadata["retrieved"],
            "expires_utc": table.metadata["expires_utc"],
            "latest_tai_minus_utc": table.entries[-1][1],
            "latest_effective_utc": table.entries[-1][0].format(),
            "entries": len(table.entries),
        },
        "ut1_snapshot": {
            "source": "https://maia.usno.navy.mil/ser7/finals.daily",
            "retrieved": "2026-10-21",
            "first": rows[0].utc_midnight.format(),
            "last": rows[-1].utc_midnight.format(),
            "rows": len(rows),
            "note": "Snapshot, not a live feed. Flag P marks predictions.",
        },
        "constants": {
            "c_m_s": str(SPEED_OF_LIGHT_M_S),
            "au_m": str(AU_METERS),
            "tt_minus_tai_s": "32.184",
            "mean_sol_earth_days": str(MEAN_SOL_EARTH_DAYS),
            "mean_sol_s": str(mean_sol_seconds()),
            "mars_sidereal_rotation_s": str(sidereal_rotation_seconds()),
            "earth_j2_omitted_seconds_per_day": str(j2["omitted_seconds_per_86400s_day"]),
        },
        "unsupported": describe_reference()["unsupported"],
    }


def _cmd_convert(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source
    target = args.target.upper()
    if source == "UTC":
        if not args.time:
            raise ChronosError("UTC input requires --time, for example 2017-01-01T00:00:00Z")
        utc = parse_utc(args.time)
        tai = utc_to_tai(utc, allow_expired=args.allow_expired)
        tt = utc_to_tt(utc, allow_expired=args.allow_expired)
        base = {
            "ok": True,
            "input": {"type": "utc-timestamp", "value": utc.format()},
            "tai_minus_utc_s": tai_minus_utc_seconds(utc, allow_expired=args.allow_expired),
            "tai": _tai_payload(tai),
            "tt": _tt_payload(tt),
            "extrapolated_past_leap_expiry": bool(args.allow_expired),
        }
        if target == "TAI":
            return base | {"result": base["tai"]}
        if target == "TT":
            return base | {"result": base["tt"]}
        if target == "UTC":
            return base | {"result": {"scale": "UTC", "value": utc.format(), "unit": "UTC calendar label"}}
        if target == "UT1":
            corr = ut1_minus_utc(utc)
            return base | {
                "result": {
                    "scale": "UT1",
                    "ut1_minus_utc_s": str(corr.ut1_minus_utc_seconds),
                    "formal_sigma_s": str(corr.formal_sigma_seconds),
                    "unit": "seconds",
                    "method": corr.method,
                    "contains_prediction": corr.contains_prediction,
                    "snapshot": corr.snapshot,
                    "note": "UT1 = UTC + (UT1−UTC). The sum is not collapsed into a fake nanosecond label.",
                }
            }
        if target in {"MSD", "MARS", "MTC"}:
            return base | _mars_payload(tt, args)
        raise ChronosError(
            f"cannot convert UTC to {args.target}. Supported targets: TAI, TT, UTC, UT1, MSD, MARS."
        )
    if source == "TAI":
        if args.tai_ns is None:
            raise ChronosError("TAI input requires --tai-ns (nanoseconds since 1972-01-01T00:00:00 TAI)")
        from chronos.core import TaiInstant

        tai = TaiInstant(args.tai_ns)
        utc = tai_to_utc(tai, allow_expired=args.allow_expired)
        if target not in {"UTC", "TT"}:
            raise ChronosError("TAI input can convert to UTC or TT")
        tt = utc_to_tt(utc, allow_expired=args.allow_expired)
        return {
            "ok": True,
            "input": {"type": "tai-instant", "nanoseconds_since_1972-01-01T00:00:00_TAI": tai.nanoseconds},
            "result": _utc_result(utc) if target == "UTC" else _tt_payload(tt),
        }
    if source == "SI":
        if args.seconds is None or target not in {"SOL", "NS"}:
            raise ChronosError("SI duration conversion requires --seconds and --to SOL or NS")
        duration = Duration.from_seconds(Decimal(args.seconds))
        if target == "NS":
            return {"ok": True, "result": {"unit": "ns", "nanoseconds": duration.nanoseconds, "scale": "SI duration"}}
        sols = sols_from_duration(duration)
        return {
            "ok": True,
            "result": {
                "unit": "mean Martian solar day (sol)",
                "sols": str(sols),
                "si_nanoseconds": duration.nanoseconds,
                "sol_definition_s": str(mean_sol_seconds()),
                "assumption": "Unit conversion by the Mars24 mean sol. Not a civil Martian timestamp.",
            },
        }
    if source == "SOL":
        if args.sols is None or target != "SI":
            raise ChronosError("SOL input requires --sols and --to SI")
        duration = duration_from_sols(Decimal(args.sols))
        return {
            "ok": True,
            "result": {
                "unit": "s",
                "seconds": str(duration.seconds()),
                "nanoseconds": duration.nanoseconds,
                "scale": "SI duration",
                "assumption": "Inverse of the Mars24 mean-sol unit conversion, rounded to 1 ns.",
            },
        }
    raise ChronosError(f"unsupported source {source}")


def _cmd_relativity(args: argparse.Namespace) -> dict[str, Any]:
    if args.model == "tdb":
        barycentric_dynamical_time()
    coordinate = Duration.from_seconds(Decimal(args.coordinate_seconds))
    if args.au is not None or args.distance_m is not None:
        if args.au is not None:
            delay = light_time_au(Decimal(args.au))
            distance = Decimal(args.au) * AU_METERS
        else:
            distance = Decimal(args.distance_m)
            delay = vacuum_light_time(distance)
        return {
            "ok": True,
            "result": {
                "model": "euclidean_vacuum_light_time",
                "distance_m": str(distance),
                "one_way_seconds": str(delay.seconds()),
                "unit": "s",
                "assumptions": [
                    "Proper length of a straight coordinate segment divided by c.",
                    "No Shapiro delay, plasma, or light-time iteration.",
                ],
            },
        }
    body = BODIES[args.body]
    radius = Decimal(args.radius_m) if args.radius_m else body.reference_radius_m
    speed = Decimal(args.speed_m_s)
    if args.model == "sr":
        result = special_relativistic_proper_time(coordinate, speed)
    elif args.model == "schwarzschild":
        if speed != 0:
            raise ChronosError(
                "The Schwarzschild stationary model requires --speed-m-s 0. "
                "Nonzero speed belongs in --model weak-field, inside its domain."
            )
        result = schwarzschild_stationary_proper_time(
            coordinate, radius, body.gm_m3_s2, body_name=body.name
        )
    else:
        result = weak_field_proper_time(
            coordinate, radius, speed, body.gm_m3_s2, body_name=body.name
        )
    return {
        "ok": True,
        "result": {
            "model": result.model,
            "proper_over_coordinate": str(result.proper_over_coordinate),
            "coordinate_seconds": str(result.coordinate.seconds()),
            "proper_seconds": str(result.proper.seconds()),
            "proper_minus_coordinate_seconds": str((result.proper - result.coordinate).seconds()),
            "unit": "s",
            "coordinate_time": result.coordinate_time_name,
            "body": body.name,
            "radius_m": str(radius),
            "speed_m_s": str(speed),
            "assumptions": list(result.assumptions),
            "not_claimed": list(result.not_claimed),
        },
    }


def _cmd_drift(args: argparse.Namespace) -> dict[str, Any]:
    clock = Clock("hypothetical", Decimal(args.y), Duration(0))
    elapsed = Duration.from_seconds(Decimal(args.seconds))
    error = accumulated_time_error(clock, elapsed)
    return {
        "ok": True,
        "result": {
            "quantity": "indicated elapsed minus ideal elapsed",
            "fractional_frequency_offset": args.y,
            "ideal_elapsed_s": str(elapsed.seconds()),
            "accumulated_error_s": str(error.seconds()),
            "accumulated_error_ns": error.nanoseconds,
            "unit": "s",
            "model": "constant fractional frequency offset, zero initial offset",
            "not_claimed": "This is not a measurement of a named atomic clock.",
        },
    }


def _cmd_sync(args: argparse.Namespace) -> dict[str, Any]:
    clock_a = Clock("A", Decimal(args.y_a), Duration(0))
    clock_b = Clock("B", Decimal(args.y_b), Duration.from_seconds(Decimal(args.offset_b_seconds)))
    exchange = two_way_exchange(
        clock_a,
        clock_b,
        ideal_send_nanoseconds=Duration.from_seconds(Decimal(args.send_seconds)).nanoseconds,
        delay_ab=Duration.from_seconds(Decimal(args.delay_ab_seconds)),
        delay_ba=Duration.from_seconds(Decimal(args.delay_ba_seconds)),
    )
    assessment = assess_exchange(clock_a, clock_b, exchange)
    return {
        "ok": True,
        "result": {
            "true_offset_b_minus_a_s": str(assessment.true_offset_b_minus_a.seconds()),
            "estimated_offset_b_minus_a_s": str(assessment.estimated_offset_b_minus_a.seconds()),
            "synchronization_error_s": str(assessment.synchronization_error.seconds()),
            "round_trip_s": str(exchange.estimated_round_trip.seconds()),
            "delay_asymmetry_s": str(assessment.delay_asymmetry.seconds()),
            "analytic_asymmetry_bias_s": str(assessment.analytic_asymmetry_bias.seconds()),
            "unit": "s",
            "assumption": assessment.note,
            "frequency_offsets": [str(assessment.frequency_offsets[0]), str(assessment.frequency_offsets[1])],
        },
    }


def _cmd_validate(_args: argparse.Namespace) -> dict[str, Any]:
    cases = run_reference_cases()
    failed = [case for case in cases if not case["passed"]]
    return {"ok": not failed, "passed": len(cases) - len(failed), "failed": len(failed), "cases": cases}


def _mars_payload(tt: Any, args: argparse.Namespace) -> dict[str, Any]:
    state = mars_solar_state(tt)
    payload: dict[str, Any] = {
        "result": {
            "scale": "Mars24 mean solar convention",
            "julian_date_tt": str(state.julian_date_tt),
            "mars_sol_date": str(state.mars_sol_date),
            "airy_mean_solar_time_hours": state.airy_mean_solar_time_hours,
            "solar_longitude_deg": state.solar_longitude_deg,
            "equation_of_time_hours": state.equation_of_time_hours,
            "convention": state.convention,
            "not_claimed": (
                "MSD and MTC are functions of TT. They are not Mars proper time "
                "and not an adopted civil standard."
            ),
        }
    }
    if args.longitude_deg is not None:
        local = local_solar_time(
            tt, float(args.longitude_deg), positive=args.longitude_positive
        )
        payload["result"]["longitude_deg"] = local.longitude_degrees
        payload["result"]["longitude_positive"] = local.longitude_positive
        payload["result"]["local_mean_solar_time_hours"] = local.local_mean_solar_time_hours
        payload["result"]["local_true_solar_time_hours"] = local.local_true_solar_time_hours
    return payload


def _tai_payload(tai: Any) -> dict[str, Any]:
    return {
        "scale": "TAI",
        "unit": "ns",
        "nanoseconds_since_1972-01-01T00:00:00_TAI": tai.nanoseconds,
        "seconds_since_origin": str(Decimal(tai.nanoseconds) / Decimal(1_000_000_000)),
    }


def _tt_payload(tt: Any) -> dict[str, Any]:
    return {
        "scale": "TT",
        "unit": "ns",
        "nanoseconds_since_1972-01-01T00:00:00_TT": tt.nanoseconds,
        "relation": "TT = TAI + 32.184 s exactly for the same event",
    }


def _utc_result(utc: Any) -> dict[str, Any]:
    return {"scale": "UTC", "value": utc.format(), "unit": "UTC calendar label"}


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
