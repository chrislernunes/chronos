# Chronos

A small, tested library for the time scales a multiplanetary log actually has to distinguish: TAI, UTC, TT, a snapshot of UT1−UTC, the NASA Mars24 mean solar convention, and three bounded relativistic clock-rate models.

The motivating question is operational, not rhetorical. Planetary rotations differ, UTC inserts leap seconds, atomic clocks have frequency offsets, signals take minutes to hours, and relativity changes clock comparisons. Chronos implements the relations that can be checked without a planetary ephemeris, and it refuses the ones that cannot.

This is not a universal clock, a civil Martian standard, or a navigation filter.

## Scope

Implemented:

- Integer-nanosecond durations and TAI/TT instants. No Unix timestamps.
- UTC ↔ TAI from 1972-01-01 through the bundled IERS leap-second expiry, including the label `23:59:60`.
- TT = TAI + 32.184 s exactly.
- UT1−UTC by linear interpolation of a vendored IERS Rapid Service snapshot.
- Mean-sol unit conversion, and Mars Sol Date / Airy mean solar time / local mean and true solar time from the Mars24 recipe.
- Special-relativistic proper time at constant inertial speed.
- Stationary Schwarzschild clock rate, and a weak-field rate taken from one stated metric.
- Constant frequency offset, and two-way time transfer with a constant delay.
- Euclidean vacuum light time (distance / c).

Not implemented, and rejected rather than approximated:

- UTC before 1972.
- TDB and TCB.
- Reduction of a Mars-surface proper time, or a spacecraft ephemeris, to TT.
- Geoid, J2, Sagnac, or GNSS clock models. A J2 sensitivity is reported and not applied.
- Live downloads. Ordinary calculations do not touch the network.

## Install

Tested on Python 3.10.22. The package itself has no third-party dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
python -m chronos validate
```

`PYTHONPATH=src` is enough to run tests without installing. Experiments need matplotlib:

```bash
pip install -e ".[experiments]"
python experiments/run_experiments.py
```

Figures and CSV files are written to `experiments/output/`, which is gitignored.

## Quick start

```bash
python -m chronos info
python -m chronos convert --from UTC --to TAI --time 2017-01-01T00:00:00Z
python -m chronos convert --from UTC --to MARS --time 2000-01-06T00:00:00Z --longitude-deg 175.5 --longitude-positive east
python -m chronos relativity --model sr --speed-m-s 7800 --coordinate-seconds 86400
python -m chronos relativity --model tdb
python -m chronos simulate drift --y 1e-13 --seconds 31557600
python -m chronos simulate sync --delay-ab-seconds 499 --delay-ba-seconds 499.2 --offset-b-seconds 0
```

JSON is the only output. A result that is not a number names its scale, unit, and assumptions. Input errors and unsupported transformations exit 2. `chronos validate` exits 1 if a published identity fails.

UTC input must end in `Z`. A numeric offset such as `+05:30` is rejected: the host time zone is not a reference scale.

## Architecture

```text
src/chronos/core.py         Duration, TaiInstant, TtInstant
src/chronos/earth.py        Gregorian dates, leap seconds, UT1 snapshot
src/chronos/mars.py         Mean sol and the Mars24 series
src/chronos/relativity.py   SR, Schwarzschild, weak-field metric
src/chronos/sync.py         Frequency offset and two-way transfer
src/chronos/reference.py    What the TT tag does and does not mean
src/chronos/cli.py          JSON command line
src/chronos/data/           Vendored IERS leap table and finals.daily
tests/                      Published values and closed-form checks
experiments/                Five scripts, one entry point
```

Each formula lives in one module. The CLI calls those functions.

### Representation

| Object | What it is | What it is not |
| --- | --- | --- |
| `Duration` | Signed SI nanoseconds | A time scale |
| `TaiInstant` | Nanoseconds after 1972-01-01T00:00:00 TAI | A Unix time |
| `TtInstant` | Nanoseconds after 1972-01-01T00:00:00 TT | Proper time on Mars |
| `UtcTimestamp` | Calendar label, second may be 60 | A continuous count |

One nanosecond is the rounding quantum. It is not an accuracy claim. Sub-nanosecond terms are rounded half-even. Python `int` is unbounded, so the type does not overflow at `int64`.

The two 1972 origins are not the same event. For one event, the TT count is the TAI count plus 32,184,000,000 ns.

## Time scales

**SI second.** Defined by fixing the caesium-133 hyperfine frequency at 9,192,631,770 Hz. BIPM, SI Brochure, 9th edition (2019).

**TAI.** International Atomic Time, the continuous scale realized by the BIPM. In this library it is the integer-nanosecond coordinate used to give UTC a leap-second-aware conversion. The library does not realize TAI from clock data.

**TT.** Terrestrial Time. The IAU relation used here is TT − TAI = 32.184 s exactly, the offset fixed so that TT continues Ephemeris Time. TT is a geocentric coordinate time. Realizations such as TT(BIPM) differ from TAI + 32.184 s at the level of the frequency steering of TAI; that difference is not modeled.

**UTC.** Coordinated Universal Time. Since 1972 it has the rate of TAI and differs by an integer number of leap seconds announced by the IERS. The bundled table is `leap-seconds.list` from the IERS Earth Orientation Centre, retrieved 2026-10-21, updated through Bulletin C 72 (6 July 2026). TAI − UTC = 37 s from 2017-01-01T00:00:00Z. The file states that it expires on 28 June 2027 (NTP `4023129600`). Instants at or after that expiry raise `LeapTableExpired` unless the caller explicitly extrapolates. Bulletin C 72 also says no leap second is introduced at the end of December 2026.

A positive leap second is the UTC label `23:59:60`. It is one distinct SI second. Adding a duration to UTC is done by going through TAI, not by adding 86400 to the clock fields.

**UT1.** Earth-rotation time. The correction UT1 − UTC is tabulated by the IERS. The bundled file is USNO `finals.daily`, retrieved 2026-10-21, covering 2026-07-23 through 2027-01-19. Rows flagged `P` are predictions in that product, not measurements. Interpolation is linear between daily 0h UTC values. Outside the file, Chronos returns an error rather than a guess. The formal error reported with an interpolation is the larger endpoint sigma, not a covariance.

A UTC day without a leap second contains 86400 SI seconds by construction. The astronomical length of day is 86400 s plus the Bulletin A LOD excess, in this snapshot a fraction of a millisecond.

**TDB.** Barycentric Dynamical Time is the time argument of planetary ephemerides. Transforming TT to TDB at a validated level needs the geocenter's barycentric state. `chronos relativity --model tdb` raises `UnsupportedTransformation`.

## Mars

The mean solar day used for unit conversion is the Mars24 divisor

```text
1 sol = 1.0274912517 × 86400 SI seconds = 88775.24414688 s
```

which rounds to the 88775.244 s (24 h 39 min 35.244 s) quoted in the NASA GISS Mars24 technical notes. The sidereal rotation quoted on the same page is 24 h 37 min 22.663 s. The solar day is longer because Mars moves along its orbit. Those are different intervals.

Mars Sol Date and Airy-mean solar time follow Mars24 equation C-2, a function of Julian Date TT:

```text
MSD = (JD_TT − 2451549.5) / 1.0274912517 + 44796.0 − 0.0009626
MTC = 24 h × fractional part of MSD
```

The epoch is the Allison & McEwen convention (MSD 0 near 1873 December 29, JD 2405522.0). Local mean solar time shifts MTC by longitude. East-positive and west-positive longitudes differ by a sign; the sign is a required argument because Mars24 uses planetographic west longitude and the IAU planetocentric convention is east-positive. Local true solar time adds the Mars24 equation of time. NASA's notes put that equation of time between about −51 min and +40 min, so a mean sol is not the apparent solar day.

NASA describes the analytic series as keeping solar longitude within about 0.008° over ±100 years of J2000, and true solar time within a few seconds from the series alone. That is a seasonal recipe. It is not a spacecraft ephemeris, and MSD is not what a clock sitting on Mars reads.

Dividing a duration by the mean sol does not produce this timestamp. Both operations exist, and they are different functions.

## Relativity

Special relativity, constant velocity, no gravity:

```text
dτ / dt = √((1 − β)(1 + β)),  β = v / c
```

`v` is a speed in m/s, `c = 299792458` exactly. Negative speeds and `v ≥ c` are errors. `v = 0` returns a rate of exactly 1, so the nanosecond count is unchanged. The product form stays finite as `β → 1`.

Stationary clock, Schwarzschild coordinate time, spherical non-rotating mass:

```text
dτ / dt = √(1 − r_s / r),  r_s = 2GM / c²
```

`r ≤ r_s` is rejected. This `t` is not TT. TT's rate is defined with the geoid potential.

Weak field, from this metric and no other combination:

```text
Φ = −GM / r
g_00 = −(1 + 2Φ / c²)
g_ij = δ_ij (1 − 2Φ / c²)
(dτ / dt)² = 1 + 2Φ / c² − (1 − 2Φ / c²) v² / c²
```

The library returns the positive square root. It also exposes the `1 + Φ/c² − v²/(2c²)` expansion so the dropped order can be seen. The weak-field function refuses `|Φ|/c² > 10⁻⁵` or `v/c > 10⁻²`. At zero speed the square root matches the Schwarzschild factor, because the spatial metric does not enter. They are not multiplied together as a third recipe.

Constants: Earth `GM = 3.986004418 × 10¹⁴ m³/s²` and equatorial radius `6378136.6 m` from IERS Conventions (2010), Table 1.1. Mars `GM = 4.282837 × 10¹³ m³/s²` and mean radius `3389.5 km` from the NASA Mars Fact Sheet, used only as spherical-model inputs. The omitted Earth J₂ piece at the equator is about `3 × 10⁻¹³` in rate, tens of nanoseconds per 86400 s day. See `earth_j2_equatorial_sensitivity`. Do not use these rates below that floor, and do not use them as a TT or TDB reduction.

Vacuum light time is `distance / c` with the IAU 2012 astronomical unit `149597870700 m`. One AU is about 499.004783836 s at nanosecond rounding. There is no Shapiro delay.

## Clocks and synchronization

A modeled clock is affine: indicated time = ideal time + offset₀ + y × elapsed. `y` is a constant fractional frequency offset. The accumulated error with zero initial offset is `y × elapsed`, rounded to 1 ns.

Optional timestamp noise is independent Gaussian, zero mean, declared σ, and a seed. It is white in the phase samples. It is not an Allan-deviation model and not an atomic-clock record.

The two-way estimate assumes symmetric delay:

```text
offset_B−A ≈ ((τ2 − τ1) + (τ3 − τ4)) / 2
```

If the one-way delays differ by Δ and the frequency offsets are zero, the estimate is wrong by Δ/2. Making `y` smaller does not remove Δ. A single exchange also does not reveal a frequency offset that has not yet accumulated.

## Data

| File | Source | Retrieved | Coverage |
| --- | --- | --- | --- |
| `data/leap_seconds.json` | [IERS leap-seconds.list](https://hpiers.obspm.fr/iers/bul/bulc/ntp/leap-seconds.list), public domain per its header | 2026-10-21 | 1972-01-01Z until expiry 2027-06-28Z. Bulletin C 72, 6 July 2026 |
| `data/finals.daily.txt` | [USNO finals.daily](https://maia.usno.navy.mil/ser7/finals.daily) | 2026-10-21 | 2026-07-23 through 2027-01-19. Flag `I` through 2026-10-20, then `P` |

Replace `finals.daily.txt` with a newer Bulletin A file of the same fixed-width layout to move the UT1 window. Do not relabel predictions as measurements. Leap seconds should be replaced only from a newer IERS `leap-seconds.list`; the NTP expiry stamp is checked against the calendar date in `chronos validate`.

## Validation

`python -m unittest discover -s tests -v` checks:

- Gregorian day counts against `datetime.date` from 1960 to 2100.
- TAI−UTC = 10 s at 1972-01-01 and 37 s at 2017-01-01.
- `2016-12-31T23:59:59Z` + 1 s = `23:59:60`, + 1 s = `2017-01-01T00:00:00Z`.
- The IERS NTP stamps 2272060800 and 4023129600 against the Gregorian calendar.
- TT − TAI = 32.184 s.
- Mars24 worked examples at 2000-01-06T00:00:00Z and the published millis 1073137591000 (2004-01-03T13:46:31Z): solar longitude, equation of time, and mean solar time within the printed tolerance.
- `√(1 − 0.6²) = 0.8` exactly.
- Two-way asymmetry bias of Δ/2 with zero frequency offset.
- The first vendored UT1−UTC sample, 0.0093744 s on 2026-07-23.

`chronos validate` runs the published subset and returns JSON. The Mars24 numbers are taken from the NASA algorithm page, not from a previous Chronos run.

## Experiments

| # | Question | Command section |
| --- | --- | --- |
| 1 | Atomic UTC day versus UT1 and LOD in the snapshot | `exp1` |
| 2 | Accumulation of a constant fractional frequency offset | `exp2` |
| 3 | Earth days of 86400 s versus Mars24 mean sols | `exp3` |
| 4 | Proper-time deficit at constant speed or at rest in the spherical model | `exp4` |
| 5 | Symmetric delay, asymmetric delay, and a frequency offset | `exp5` |

Reproduction:

```bash
python experiments/run_experiments.py
```

`experiments/output/summary.json` records the numbers those runs produced. Charts use the same numbers. Nothing in the experiments predicts the future performance of a real clock.

## Limitations

- Leap-second coverage stops at the IERS file expiry. A later Bulletin C can insert a leap second that this snapshot does not know.
- UT1 coverage is a short rapid-service window, linearly interpolated.
- Mars24 is a mean-solar convention of TT. Apparent solar time, lander coordinates, and a physical Mars clock are additional problems.
- The relativistic models are constant-condition evaluations. They are not integrated worldlines.
- No claim is made about operational deep-space time transfer, which needs an ephemeris, a light-time solution, and a stated reference frame.

## References

- BIPM, *The International System of Units (SI)*, 9th edition, 2019. Definition of the second.
- IAU Resolution A4 (1991) and subsequent notes: TT − TAI = 32.184 s at the continuity epoch with Ephemeris Time. BIPM discusses the same offset under Terrestrial Time.
- IERS Conventions (2010), Petit & Luzum (eds.), IERS Technical Note 36, Table 1.1. `GM`, equatorial radius, `J₂` for the Earth model and its sensitivity.
- IERS Bulletin C 72, 6 July 2026, Earth Orientation Center, Paris Observatory. No leap second at the end of December 2026; UTC − TAI = −37 s.
- IERS/USNO `leap-seconds.list` and `finals.daily` as vendored above.
- Allison, M. & McEwen, M. (2000), *Planet. Space Sci.* 48, 215–235. Mean sol and the solar-time recipe.
- NASA GISS Mars24, “Algorithm and Worked Examples”, algorithm date 2025-01-07, and “Technical Notes on Mars Solar Time”. https://www.giss.nasa.gov/tools/mars24/
- IAU 2012 astronomical unit, 149597870700 m exactly. Speed of light, 299792458 m/s exactly, from the SI.
- NASA GSFC Mars Fact Sheet, `GM` and mean radius used in the spherical Mars illustration. https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html

## Development

```bash
python -m unittest discover -s tests -v
python -m chronos info
python -m chronos validate
```

Continuous integration is `.github/workflows/tests.yml` on Python 3.10, 3.11, and 3.12: install, unittest, and the three CLI commands above. That workflow also runs the browser engine against `tests/fixtures/browser_parity.json`.

## Browser console

The source of the browser page is `site/`. It does not call a server. `.github/workflows/pages.yml` installs from the lockfile, runs the browser parity tests, builds `site/dist`, and deploys that directory with the GitHub Pages actions. Vite's `base` is `/chronos/`. The address is [chrislernunes.github.io/chronos](https://chrislernunes.github.io/chronos/) when the repository Pages source is **GitHub Actions**. A branch source does not serve the artifact.

The Python package is the reference. The page uses integer counts for UTC, TAI, and TT, and IEEE-754 for the Mars24 series and the relativistic rates. Nanosecond rounding of those irrational rates belongs to the Python package, not to the page.
