"""Five reproducible experiments. Outputs go to experiments/output/.

Run from the repository root, with the package importable:

    pip install -e ".[experiments]"
    python experiments/run_experiments.py

No network access. Earth-rotation results use the bundled IERS snapshot only.
Clock results are hypothetical constant frequency offsets, not instrument logs.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from chronos.core import NANOSECONDS_PER_SECOND, Duration
from chronos.earth import length_of_day_seconds, load_eop_rows, parse_utc, utc_to_tt, ut1_minus_utc
from chronos.mars import MEAN_SOL_EARTH_DAYS, mars_solar_state, mean_sol_seconds, sols_from_duration
from chronos.relativity import (
    EARTH,
    schwarzschild_stationary_proper_time,
    special_relativistic_proper_time,
    weak_field_proper_time,
)
from chronos.sync import Clock, assess_exchange, two_way_exchange

OUT = Path(__file__).resolve().parent / "output"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "experiments": [
            experiment_rotation(),
            experiment_frequency(),
            experiment_sols(),
            experiment_proper_time(),
            experiment_sync(),
        ]
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"ok": True, "output": str(OUT)}, indent=2))


def experiment_rotation() -> dict:
    """How atomic UTC days and the astronomical length of day differ."""

    rows = [row for row in load_eop_rows() if row.flag == "I" and row.lod_milliseconds is not None]
    path = OUT / "exp1_rotation.csv"
    residuals = []
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "date",
                "ut1_minus_utc_s",
                "lod_ms",
                "astronomical_day_s",
                "utc_day_without_leap_s",
                "next_day_dut1_change_s",
                "minus_lod_s",
            ]
        )
        for index, row in enumerate(rows[:-1]):
            nxt = rows[index + 1]
            change = nxt.ut1_minus_utc - row.ut1_minus_utc
            minus_lod = -(row.lod_milliseconds / Decimal(1000))
            residuals.append(abs(change - minus_lod))
            writer.writerow(
                [
                    f"{row.year:04d}-{row.month:02d}-{row.day:02d}",
                    str(row.ut1_minus_utc),
                    str(row.lod_milliseconds),
                    str(length_of_day_seconds(row.lod_milliseconds)),
                    "86400",
                    str(change),
                    str(minus_lod),
                ]
            )
    rms = (sum(item * item for item in residuals) / Decimal(len(residuals))).sqrt()
    _plot_rotation(rows)
    return {
        "id": "exp1_atomic_vs_rotation",
        "question": "Over the bundled IERS snapshot, how does UT1-UTC move relative to the 86400 s UTC day, and does the tabulated LOD match that motion?",
        "result": {
            "observed_rows_with_lod": len(rows),
            "first": f"{rows[0].year:04d}-{rows[0].month:02d}-{rows[0].day:02d}",
            "last": f"{rows[-1].year:04d}-{rows[-1].month:02d}-{rows[-1].day:02d}",
            "ut1_utc_start_s": str(rows[0].ut1_minus_utc),
            "ut1_utc_end_s": str(rows[-1].ut1_minus_utc),
            "rms_one_day_residual_s": str(rms),
            "interpretation": (
                "A UTC day in this window has exactly 86400 SI seconds because no leap "
                "second occurs. The astronomical day differs from that by the tabulated "
                "LOD, a fraction of a millisecond here. The one-day change in UT1-UTC "
                "tracks -LOD. That agreement checks the column units; Bulletin A derives "
                "LOD from UT1, so it is not an independent geophysical measurement."
            ),
        },
        "files": ["exp1_rotation.csv", "exp1_rotation.png"],
    }


def experiment_frequency() -> dict:
    offsets = [Decimal("1e-15"), Decimal("1e-13"), Decimal("1e-11"), Decimal("1e-9")]
    horizons = [
        ("1 day", Decimal(86400)),
        ("30 days", Decimal(30 * 86400)),
        ("365.25 days", Decimal("365.25") * Decimal(86400)),
        ("10 Julian years", Decimal(10 * 36525) / Decimal(10) * Decimal(86400)),
    ]
    # 10 Julian years = 3652.5 days. Decimal(10) * 365.25 * 86400.
    horizons[3] = ("10 Julian years", Decimal("3652.5") * Decimal(86400))
    path = OUT / "exp2_frequency.csv"
    rows = []
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fractional_frequency_offset", "horizon", "ideal_elapsed_s", "accumulated_error_s"])
        for y in offsets:
            clock = Clock("hypothetical", y, Duration(0))
            for name, seconds in horizons:
                elapsed = Duration.from_seconds(seconds)
                from chronos.sync import accumulated_time_error

                error = accumulated_time_error(clock, elapsed)
                rows.append((y, name, seconds, error.seconds()))
                writer.writerow([str(y), name, str(seconds), str(error.seconds())])
    _plot_frequency(rows)
    return {
        "id": "exp2_frequency_accumulation",
        "question": "How large is the time error from a constant fractional frequency offset after days, months, and years?",
        "result": {
            "example_1e-13_after_365.25_days_s": str(
                next(row[3] for row in rows if row[0] == Decimal("1e-13") and row[1] == "365.25 days")
            ),
            "model": "error = y × elapsed, rounded to 1 ns. Zero initial offset.",
            "not_claimed": "These offsets are hypothetical. They are not specifications or measurements of a named clock.",
        },
        "files": ["exp2_frequency.csv", "exp2_frequency.png"],
    }


def experiment_sols() -> dict:
    sol = mean_sol_seconds()
    spans = [Decimal(1), Decimal(10), Decimal(100), Decimal("668.5921"), Decimal("686.9725")]
    path = OUT / "exp3_sols.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["earth_days_of_86400_s", "si_seconds", "mean_sols"])
        plotted = []
        for days in spans:
            duration = Duration.from_seconds(days * Decimal(86400))
            sols = sols_from_duration(duration)
            plotted.append((days, sols))
            writer.writerow([str(days), str(duration.seconds()), str(sols)])
    tropical_sols = Decimal("686.9725") / MEAN_SOL_EARTH_DAYS
    state = mars_solar_state(utc_to_tt(parse_utc("2000-01-06T00:00:00Z")))
    _plot_sols(plotted)
    return {
        "id": "exp3_earth_days_and_sols",
        "question": "How many Mars24 mean sols are there in an integer number of 86400 s Earth days, and does the quoted tropical year match the mean sol?",
        "result": {
            "mean_sol_s": str(sol),
            "mean_sol_earth_days": str(MEAN_SOL_EARTH_DAYS),
            "nasa_tropical_year_days": "686.9725",
            "that_interval_in_mean_sols": str(tropical_sols),
            "nasa_quoted_tropical_year_sols": "668.5921",
            "absolute_difference_sols": str(abs(tropical_sols - Decimal("668.5921"))),
            "msd_at_2000-01-06T00:00:00Z": str(state.mars_sol_date),
            "assumption": "Mean sol only. Apparent solar days differ by the equation of time, up to about an hour in the Mars24 notes.",
        },
        "files": ["exp3_sols.csv", "exp3_sols.png"],
    }


def experiment_proper_time() -> dict:
    day = Duration(86400 * NANOSECONDS_PER_SECOND)
    speeds = [
        Decimal(0),
        Decimal(7800),
        Decimal(29780),
        Decimal("29979245.8"),
    ]
    path = OUT / "exp4_proper_time.csv"
    series = []
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["model", "speed_m_s", "radius_m", "coordinate_s", "proper_minus_coordinate_s"])
        for speed in speeds:
            result = special_relativistic_proper_time(day, speed)
            deficit = (result.proper - result.coordinate).seconds()
            series.append(("sr", speed, deficit))
            writer.writerow(["sr", str(speed), "", "86400", str(deficit)])
        stationary = schwarzschild_stationary_proper_time(
            day, EARTH.reference_radius_m, EARTH.gm_m3_s2, body_name="earth"
        )
        weak = weak_field_proper_time(
            day, EARTH.reference_radius_m, Decimal(7800), EARTH.gm_m3_s2, body_name="earth"
        )
        writer.writerow(
            [
                "schwarzschild_stationary_earth_equatorial_radius",
                "0",
                str(EARTH.reference_radius_m),
                "86400",
                str((stationary.proper - stationary.coordinate).seconds()),
            ]
        )
        writer.writerow(
            [
                "weak_field_sqrt_7800_m_s",
                "7800",
                str(EARTH.reference_radius_m),
                "86400",
                str((weak.proper - weak.coordinate).seconds()),
            ]
        )
    _plot_sr(series)
    return {
        "id": "exp4_proper_time",
        "question": "For a constant coordinate speed, or a stationary spherical clock, how large is one day of proper-time deficit?",
        "result": {
            "sr_7800_m_s_deficit_s": str(series[1][2]),
            "schwarzschild_earth_radius_deficit_s": str((stationary.proper - stationary.coordinate).seconds()),
            "weak_field_7800_deficit_s": str((weak.proper - weak.coordinate).seconds()),
            "coordinate_time": "SR uses inertial t. The other two use their own metric t, not TT.",
            "not_claimed": "7800 m/s is only an illustrative speed. This is not a low-Earth-orbit integration and not a navigation result.",
        },
        "files": ["exp4_proper_time.csv", "exp4_proper_time.png"],
    }


def experiment_sync() -> dict:
    light = Duration.from_seconds(Decimal("149597870700") / Decimal("299792458"))
    cases = []
    specs = [
        ("symmetric_1au_zero_offset", light, light, Decimal(0), Decimal(0), Decimal(0)),
        ("asymmetric_plus_0.2s", light, light + Duration.from_seconds(Decimal("0.2")), Decimal(0), Decimal(0), Decimal(0)),
        ("symmetric_with_y_1e-12", light, light, Decimal(0), Decimal(0), Decimal("1e-12")),
    ]
    path = OUT / "exp5_sync.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["case", "send_s", "true_offset_s", "estimated_offset_s", "sync_error_s", "asymmetry_bias_s"]
        )
        for name, dab, dba, offset_b, y_a, y_b in specs:
            for send_s in (Decimal(0), Decimal(86400), Decimal(86400 * 365)):
                clock_a = Clock("A", y_a, Duration(0))
                clock_b = Clock("B", y_b, Duration.from_seconds(offset_b))
                exchange = two_way_exchange(
                    clock_a,
                    clock_b,
                    ideal_send_nanoseconds=Duration.from_seconds(send_s).nanoseconds,
                    delay_ab=dab,
                    delay_ba=dba,
                )
                assessment = assess_exchange(clock_a, clock_b, exchange)
                row = {
                    "case": name,
                    "send_s": str(send_s),
                    "true_offset_s": str(assessment.true_offset_b_minus_a.seconds()),
                    "estimated_offset_s": str(assessment.estimated_offset_b_minus_a.seconds()),
                    "sync_error_s": str(assessment.synchronization_error.seconds()),
                    "asymmetry_bias_s": str(assessment.analytic_asymmetry_bias.seconds()),
                }
                cases.append(row)
                writer.writerow(
                    [
                        row["case"],
                        row["send_s"],
                        row["true_offset_s"],
                        row["estimated_offset_s"],
                        row["sync_error_s"],
                        row["asymmetry_bias_s"],
                    ]
                )
    _plot_sync(cases)
    asymmetric = next(row for row in cases if row["case"] == "asymmetric_plus_0.2s" and row["send_s"] == "0")
    drifted = [row for row in cases if row["case"] == "symmetric_with_y_1e-12"]
    return {
        "id": "exp5_sync_delay",
        "question": "Does a symmetric-delay two-way exchange remove a propagation delay, and does a smaller clock still remove an asymmetric delay?",
        "result": {
            "one_au_delay_s": str(light.seconds()),
            "asymmetric_error_s": asymmetric["sync_error_s"],
            "asymmetric_analytic_bias_s": asymmetric["asymmetry_bias_s"],
            "y_1e-12_error_at_0_s": drifted[0]["sync_error_s"],
            "y_1e-12_error_at_365_days_s": drifted[2]["sync_error_s"],
            "interpretation": (
                "With equal one-way delays the estimate matches the true offset. "
                "A 0.2 s asymmetry biases it by 0.1 s even when both frequency offsets "
                "are zero. A nonzero frequency offset is a different error: one exchange "
                "can still look good at that epoch, and the offset then grows as y × t. "
                "A better clock does not measure the path."
            ),
        },
        "files": ["exp5_sync.csv", "exp5_sync.png"],
    }


def _plot_rotation(rows) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dates = [date(row.year, row.month, row.day) for row in rows]
    values = [float(row.ut1_minus_utc) for row in rows]
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.plot(dates, values, color="#8c3b22", lw=1.6)
    ax.set_title("UT1 − UTC in the bundled IERS rapid snapshot")
    ax.set_ylabel("UT1 − UTC (s)")
    ax.set_xlabel("UTC date at 0h")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT / "exp1_rotation.png", dpi=140)
    plt.close(fig)


def _plot_frequency(rows) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    offsets = []
    for y, name, _seconds, error in rows:
        if y not in offsets:
            offsets.append(y)
    for y in offsets:
        subset = [row for row in rows if row[0] == y]
        ax.plot(
            [float(row[2]) / 86400 for row in subset],
            [abs(float(row[3])) for row in subset],
            marker="o",
            lw=1.4,
            label=f"y = {y}",
        )
    ax.set_yscale("log")
    ax.set_xlabel("Ideal elapsed time (days of 86400 s)")
    ax.set_ylabel("|accumulated error| (s)")
    ax.set_title("Constant fractional frequency offset integrates as y × t")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "exp2_frequency.png", dpi=140)
    plt.close(fig)


def _plot_sols(plotted) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    xs = [float(item[0]) for item in plotted]
    ys = [float(item[1]) for item in plotted]
    ax.plot(xs, ys, color="#1b1916", marker="o")
    ax.plot(xs, xs, color="#8c3b22", ls="--", lw=1, label="one Earth day = one sol (false)")
    ax.set_xlabel("Elapsed time (Earth days of 86400 SI seconds)")
    ax.set_ylabel("Mars24 mean sols")
    ax.set_title("Mean sols are not Earth days")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "exp3_sols.png", dpi=140)
    plt.close(fig)


def _plot_sr(series) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    labels = ["0", "7.8 km/s", "29.8 km/s", "0.1 c"]
    deficits = [abs(float(item[2])) for item in series]
    ax.bar(labels, deficits, color="#8c3b22")
    ax.set_yscale("log")
    ax.set_ylabel("|proper − coordinate| over 86400 s (s)")
    ax.set_xlabel("Constant inertial speed")
    ax.set_title("Special-relativistic deficit only. No gravity.")
    fig.tight_layout()
    fig.savefig(OUT / "exp4_proper_time.png", dpi=140)
    plt.close(fig)


def _plot_sync(cases) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    drifted = [row for row in cases if row["case"] == "symmetric_with_y_1e-12"]
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    days = [float(row["send_s"]) / 86400 for row in drifted]
    ax.plot(
        days,
        [abs(float(row["true_offset_s"])) for row in drifted],
        color="#8c3b22",
        marker="o",
        label="|true offset|, symmetric delay, y = 10⁻¹²",
    )
    ax.plot(
        days,
        [abs(float(row["sync_error_s"])) for row in drifted],
        color="#1b1916",
        marker="o",
        label="|sync error| of that exchange",
    )
    bias = abs(float(next(row["sync_error_s"] for row in cases if row["case"].startswith("asymmetric"))))
    ax.axhline(bias, color="#6e675e", ls="--", label="sync error from 0.2 s asymmetry, y = 0")
    ax.set_xlabel("Ideal time of the exchange (days)")
    ax.set_ylabel("seconds")
    ax.set_title("Frequency error accumulates. Asymmetry biases one exchange.")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "exp5_sync.png", dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    main()
