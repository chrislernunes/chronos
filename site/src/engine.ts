/**
 * Browser port of the Chronos timekeeping relations.
 *
 * Leap seconds, the Mars24 series, and the closed-form clock models match the
 * Python package. Irrational rates use IEEE-754. The Python package is the
 * reference for nanosecond rounding of those rates. UTC, TAI, and TT counts
 * here are exact integers.
 */

import { EOP_ROWS, LEAP_ENTRIES, LEAP_EXPIRES, type EopRow } from "./tables.ts";

export const NS = 1_000_000_000n;
export const TT_MINUS_TAI_NS = 32_184_000_000n;
export const C_M_S = 299_792_458;
export const AU_M = 149_597_870_700;
export const MEAN_SOL_NS = 88_775_244_146_880n;
export const MEAN_SOL_DAYS = 1.0274912517;
export const EARTH_GM = 3.986004418e14;
export const EARTH_RADIUS_M = 6_378_136.6;
export const MARS_GM = 4.282837e13;
export const MARS_RADIUS_M = 3_389_500;

export class ChronosError extends Error {}
export class InvalidInput extends ChronosError {}
export class InvalidLeapSecond extends InvalidInput {}
export class DataCoverageError extends ChronosError {}
export class LeapTableExpired extends DataCoverageError {}
export class UnsupportedTransformation extends ChronosError {}

export type Utc = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  nanosecond: number;
};

type Bound = { utc: Utc; offset: number; taiSeconds: bigint };

const bounds: Bound[] = LEAP_ENTRIES.map((entry) => {
  const utc = parseUtc(entry.effective);
  return {
    utc,
    offset: entry.taiMinusUtc,
    taiSeconds: posixLike(utc) + BigInt(entry.taiMinusUtc),
  };
});

const expiry = parseUtc(LEAP_EXPIRES);

export function parseUtc(text: string): Utc {
  if (!text.endsWith("Z")) {
    throw new InvalidInput("UTC timestamps must end with Z. Offsets and local time are rejected.");
  }
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$/.exec(text);
  if (!match) {
    throw new InvalidInput("Use 2017-01-01T00:00:00Z or a leap label 2016-12-31T23:59:60Z.");
  }
  const stamp: Utc = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6]),
    nanosecond: Number((match[7] ?? "").padEnd(9, "0")),
  };
  if (!validDate(stamp.year, stamp.month, stamp.day)) throw new InvalidInput("Invalid Gregorian date.");
  if (stamp.hour > 23 || stamp.minute > 59 || stamp.second > 60) {
    throw new InvalidInput("Clock fields are out of range.");
  }
  return stamp;
}

export function formatUtc(utc: Utc): string {
  const ns = String(utc.nanosecond).padStart(9, "0");
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(utc.year, 4)}-${p(utc.month)}-${p(utc.day)}T${p(utc.hour)}:${p(utc.minute)}:${p(utc.second)}.${ns}Z`;
}

export function utcToTaiNs(utc: Utc, allowExpired = false): bigint {
  const offset = utc.second === 60 ? offsetDuringLeap(utc, allowExpired) : offsetAt(utc, allowExpired);
  if (utc.second === 60 && !isLeapLabel(utc, allowExpired)) {
    throw new InvalidLeapSecond(`${formatUtc(utc)} is not a positive leap second in the bundled IERS table.`);
  }
  return (posixLike(utc) + BigInt(offset)) * NS + BigInt(utc.nanosecond);
}

export function taiToUtc(taiNs: bigint, allowExpired = false): Utc {
  if (taiNs < 10n * NS) {
    throw new DataCoverageError("This UTC mapping starts at 1972-01-01T00:00:10 TAI.");
  }
  const taiSeconds = taiNs / NS;
  const nanosecond = Number(taiNs % NS);
  let index = -1;
  for (let i = 0; i < bounds.length; i += 1) {
    if (bounds[i].taiSeconds <= taiSeconds) index = i;
    else break;
  }
  if (index < 0) throw new DataCoverageError("TAI instant precedes the leap-second table.");
  const offset = BigInt(bounds[index].offset);
  if (index + 1 < bounds.length && taiSeconds === bounds[index + 1].taiSeconds - 1n) {
    const nextOffset = bounds[index + 1].offset;
    if (nextOffset === bounds[index].offset + 1) {
      const prev = shiftDays(bounds[index + 1].utc, -1);
      const stamp = { ...prev, hour: 23, minute: 59, second: 60, nanosecond };
      requireCoverage(stamp, allowExpired);
      return stamp;
    }
    if (nextOffset < bounds[index].offset) {
      throw new DataCoverageError(
        "A negative leap second would skip a UTC label. None has been announced; this snapshot does not implement one.",
      );
    }
  }
  const stamp = fromPosix(taiSeconds - offset, nanosecond);
  requireCoverage(stamp, allowExpired);
  return stamp;
}

export function addNanoseconds(utc: Utc, delta: bigint, allowExpired = false): Utc {
  return taiToUtc(utcToTaiNs(utc, allowExpired) + delta, allowExpired);
}

export function taiMinusUtcSeconds(utc: Utc, allowExpired = false): number {
  return utc.second === 60 ? offsetDuringLeap(utc, allowExpired) : offsetAt(utc, allowExpired);
}

export function ttNanoseconds(taiNs: bigint): bigint {
  return taiNs + TT_MINUS_TAI_NS;
}

export function julianDateTt(ttNs: bigint): number {
  const day = 86_400n * NS;
  const j2000 = (10_227n * 86_400n + 12n * 3_600n) * NS;
  let delta = ttNs - j2000;
  let days = delta / day;
  let rem = delta % day;
  if (rem < 0n) {
    days -= 1n;
    rem += day;
  }
  return 2_451_545 + Number(days) + Number(rem) / Number(day);
}

export type Ut1Result = {
  seconds: number;
  sigma: number;
  prediction: boolean;
  method: string;
};

export function ut1MinusUtc(utc: Utc): Ut1Result {
  if (utc.second === 60) throw new InvalidInput("UT1 interpolation is not defined on a leap-second label.");
  const target = Number(posixLike(utc));
  const series = EOP_ROWS.map((row) => ({ row, t: Number(posixLike(parseUtc(`${row.date}T00:00:00Z`))) }));
  if (target < series[0].t || target > series[series.length - 1].t) {
    throw new DataCoverageError(
      `UT1 snapshot covers ${series[0].row.date} through ${series[series.length - 1].row.date} only.`,
    );
  }
  let right = 0;
  while (right < series.length && series[right].t < target) right += 1;
  if (series[right].t === target) {
    return finishUt1(series[right].row, series[right].row, series[right].row.ut1Utc, false);
  }
  const left = series[right - 1];
  const span = series[right].t - left.t;
  const weight = (target - left.t) / span;
  const value = left.row.ut1Utc + (series[right].row.ut1Utc - left.row.ut1Utc) * weight;
  return finishUt1(left.row, series[right].row, value, true);
}

export type MarsState = {
  julianDateTt: number;
  marsSolDate: number;
  meanSolarHours: number;
  solarLongitudeDeg: number;
  equationOfTimeHours: number;
  meanAnomalyDeg: number;
};

const PERTURBERS: [number, number, number][] = [
  [0.0071, 2.2353, 49.409],
  [0.0057, 2.7543, 168.173],
  [0.0039, 1.1177, 191.837],
  [0.0037, 15.7866, 21.736],
  [0.0021, 2.1354, 15.704],
  [0.002, 2.4694, 95.528],
  [0.0018, 32.8493, 49.095],
];

export function marsSolarState(ttNs: bigint): MarsState {
  const jd = julianDateTt(ttNs);
  const dt = jd - 2_451_545;
  const meanAnomaly = wrap360(19.3871 + 0.52402073 * dt);
  const fms = wrap360(270.3871 + 0.524038496 * dt);
  let pbs = 0;
  for (const [amplitude, period, phase] of PERTURBERS) {
    pbs += amplitude * Math.cos(((0.985626 * dt) / period + phase) * (Math.PI / 180));
  }
  const sind = (deg: number) => Math.sin(deg * (Math.PI / 180));
  const eoc =
    (10.691 + 3e-7 * dt) * sind(meanAnomaly) +
    0.623 * sind(2 * meanAnomaly) +
    0.05 * sind(3 * meanAnomaly) +
    0.005 * sind(4 * meanAnomaly) +
    0.0005 * sind(5 * meanAnomaly) +
    pbs;
  const solarLongitude = wrap360(fms + eoc);
  const eotDeg =
    2.861 * sind(2 * solarLongitude) -
    0.071 * sind(4 * solarLongitude) +
    0.002 * sind(6 * solarLongitude) -
    eoc;
  const msd = (jd - 2_451_549.5) / MEAN_SOL_DAYS + 44_796 - 0.0009626;
  const frac = msd - Math.floor(msd);
  return {
    julianDateTt: jd,
    marsSolDate: msd,
    meanSolarHours: (frac * 24) % 24,
    solarLongitudeDeg: solarLongitude,
    equationOfTimeHours: eotDeg / 15,
    meanAnomalyDeg: meanAnomaly,
  };
}

export function localSolarTime(ttNs: bigint, longitudeDeg: number, positive: "east" | "west") {
  const state = marsSolarState(ttNs);
  const signed = positive === "east" ? longitudeDeg : -longitudeDeg;
  const mean = mod24(state.meanSolarHours + signed / 15);
  return {
    state,
    localMeanHours: mean,
    localTrueHours: mod24(mean + state.equationOfTimeHours),
  };
}

export function solsInSeconds(seconds: number): number {
  return (seconds * 1e9) / Number(MEAN_SOL_NS);
}

export function srRate(speedMps: number): number {
  if (!Number.isFinite(speedMps) || speedMps < 0) throw new InvalidInput("Speed must be ≥ 0 m/s.");
  if (speedMps >= C_M_S) throw new InvalidInput("Speed must be strictly below c. Superluminal values are rejected.");
  if (speedMps === 0) return 1;
  const beta = speedMps / C_M_S;
  return Math.sqrt((1 - beta) * (1 + beta));
}

export function schwarzschildRate(radiusM: number, gm = EARTH_GM): number {
  const rs = (2 * gm) / C_M_S ** 2;
  if (!(radiusM > rs)) throw new InvalidInput("Radius must lie outside the Schwarzschild radius.");
  return Math.sqrt(1 - rs / radiusM);
}

export function weakFieldRate(radiusM: number, speedMps: number, gm = EARTH_GM): number {
  const phi = -gm / (C_M_S ** 2 * radiusM);
  const beta2 = (speedMps / C_M_S) ** 2;
  if (Math.abs(phi) > 1e-5 || speedMps / C_M_S > 1e-2) {
    throw new InvalidInput("Outside the weak-field domain (|Φ|/c² ≤ 1e-5 and v/c ≤ 0.01).");
  }
  srRate(speedMps);
  schwarzschildRate(radiusM, gm);
  const inside = 1 + 2 * phi - (1 - 2 * phi) * beta2;
  if (inside <= 0) throw new InvalidInput("Metric factor is not positive.");
  return Math.sqrt(inside);
}

export function lightTimeSeconds(distanceM: number): number {
  if (!Number.isFinite(distanceM) || distanceM < 0) throw new InvalidInput("Distance must be ≥ 0.");
  return distanceM / C_M_S;
}

/** Half-even nanoseconds of distance/c. Matches the Python reference for integer metres. */
export function lightTimeNanoseconds(distanceM: number): bigint {
  if (!Number.isFinite(distanceM) || distanceM < 0) throw new InvalidInput("Distance must be ≥ 0.");
  if (!Number.isSafeInteger(distanceM)) {
    throw new InvalidInput("Nanosecond light time requires an integer distance in metres.");
  }
  const numerator = BigInt(distanceM) * NS;
  const denominator = BigInt(C_M_S);
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  const twice = remainder * 2n;
  if (twice > denominator || (twice === denominator && quotient % 2n === 1n)) return quotient + 1n;
  return quotient;
}

export function unsupported(kind: "tdb" | "mars-proper-time"): never {
  if (kind === "tdb") {
    throw new UnsupportedTransformation(
      "TDB/TCB conversion is unsupported. It requires a planetary ephemeris for the geocenter's barycentric state. A two-term sine is not returned.",
    );
  }
  throw new UnsupportedTransformation(
    "A Mars-surface proper time is not reduced to TT. Mars24 is a function of Terrestrial Time, not a clock on Mars.",
  );
}

export function accumulatedErrorSeconds(y: number, elapsedSeconds: number): number {
  return y * elapsedSeconds;
}

export type SyncResult = {
  trueOffsetS: number;
  estimatedOffsetS: number;
  errorS: number;
  roundTripS: number;
  asymmetryBiasS: number;
};

export function twoWaySync(input: {
  delayAbS: number;
  delayBaS: number;
  offsetBS: number;
  yA: number;
  yB: number;
  sendS: number;
}): SyncResult {
  if (input.delayAbS < 0 || input.delayBaS < 0) throw new InvalidInput("Delays must be ≥ 0.");
  const ind = (y: number, ideal: number, offset: number) => ideal + offset + y * (ideal - 0);
  const t1 = input.sendS;
  const t2 = t1 + input.delayAbS;
  const t3 = t2;
  const t4 = t3 + input.delayBaS;
  const tau1 = ind(input.yA, t1, 0);
  const tau2 = ind(input.yB, t2, input.offsetBS);
  const tau3 = ind(input.yB, t3, input.offsetBS);
  const tau4 = ind(input.yA, t4, 0);
  const estimated = ((tau2 - tau1) + (tau3 - tau4)) / 2;
  const trueOffset = ind(input.yB, t1, input.offsetBS) - ind(input.yA, t1, 0);
  return {
    trueOffsetS: trueOffset,
    estimatedOffsetS: estimated,
    errorS: estimated - trueOffset,
    roundTripS: tau4 - tau1 - (tau3 - tau2),
    asymmetryBiasS: (input.delayAbS - input.delayBaS) / 2,
  };
}

export type Check = { name: string; passed: boolean; detail: string };

export function referenceChecks(): Check[] {
  const out: Check[] = [];
  const check = (name: string, run: () => void) => {
    try {
      run();
      out.push({ name, passed: true, detail: "ok" });
    } catch (error) {
      out.push({ name, passed: false, detail: error instanceof Error ? error.message : String(error) });
    }
  };
  check("1972-01-01 TAI−UTC = 10", () => {
    const utc = parseUtc("1972-01-01T00:00:00Z");
    if (taiMinusUtcSeconds(utc) !== 10) throw new Error("offset");
    if (utcToTaiNs(utc) !== 10n * NS) throw new Error("tai");
  });
  check("2017-01-01 TAI−UTC = 37", () => {
    if (taiMinusUtcSeconds(parseUtc("2017-01-01T00:00:00Z")) !== 37) throw new Error("offset");
  });
  check("2016-12-31 leap label", () => {
    const leap = addNanoseconds(parseUtc("2016-12-31T23:59:59Z"), NS);
    const next = addNanoseconds(leap, NS);
    if (formatUtc(leap) !== "2016-12-31T23:59:60.000000000Z") throw new Error(formatUtc(leap));
    if (formatUtc(next) !== "2017-01-01T00:00:00.000000000Z") throw new Error(formatUtc(next));
    if (taiMinusUtcSeconds(leap) !== 36) throw new Error("pre-leap offset");
    if (taiMinusUtcSeconds(next) !== 37) throw new Error("post-leap offset");
  });
  check("Mars24 2000-01-06", () => {
    const state = marsSolarState(ttNanoseconds(utcToTaiNs(parseUtc("2000-01-06T00:00:00Z"))));
    near(state.solarLongitudeDeg, 277.18758, 5e-4, "Ls");
    near(state.equationOfTimeHours, -0.34585, 5e-5, "EOT");
    near(state.meanSolarHours, 23.99425, 5e-4, "MST");
    near(state.meanAnomalyDeg, 21.74558, 5e-4, "M");
  });
  check("Mars24 millis 1073137591000", () => {
    const state = marsSolarState(ttNanoseconds(utcToTaiNs(parseUtc("2004-01-03T13:46:31Z"))));
    near(state.meanSolarHours, 13.16537, 5e-4, "MST");
    near(state.solarLongitudeDeg, 327.32416, 5e-3, "Ls");
    near(state.equationOfTimeHours, -0.85170, 5e-4, "EOT");
  });
  check("√(1−0.6²) = 0.8", () => {
    const rate = srRate(0.6 * C_M_S);
    if (Math.abs(rate - 0.8) > 1e-12) throw new Error(String(rate));
  });
  check("v = c rejected", () => {
    let threw = false;
    try {
      srRate(C_M_S);
    } catch {
      threw = true;
    }
    if (!threw) throw new Error("accepted");
  });
  check("TDB and Mars proper time are refused", () => {
    for (const kind of ["tdb", "mars-proper-time"] as const) {
      let threw = false;
      try {
        unsupported(kind);
      } catch (error) {
        threw = error instanceof UnsupportedTransformation;
      }
      if (!threw) throw new Error(kind);
    }
  });
  check("asymmetry bias Δ/2", () => {
    const sync = twoWaySync({
      delayAbS: 10,
      delayBaS: 4,
      offsetBS: 5,
      yA: 0,
      yB: 0,
      sendS: 0,
    });
    if (Math.abs(sync.estimatedOffsetS - 8) > 1e-12) throw new Error(String(sync.estimatedOffsetS));
    if (Math.abs(sync.errorS - 3) > 1e-12) throw new Error(String(sync.errorS));
  });
  return out;
}

export const COVERAGE = {
  leapExpires: LEAP_EXPIRES,
  taiMinusUtc: 37,
  ut1First: EOP_ROWS[0].date,
  ut1Last: EOP_ROWS[EOP_ROWS.length - 1].date,
  observedThrough: EOP_ROWS.filter((row) => row.flag === "I").at(-1)?.date ?? EOP_ROWS[0].date,
};

function near(actual: number, expected: number, tol: number, name: string) {
  if (Math.abs(actual - expected) > tol) {
    throw new Error(`${name}: ${actual} vs ${expected}`);
  }
}

function finishUt1(left: EopRow, right: EopRow, seconds: number, interpolated: boolean): Ut1Result {
  return {
    seconds,
    sigma: Math.max(left.sigma, right.sigma),
    prediction: left.flag === "P" || right.flag === "P",
    method: interpolated
      ? "Linear interpolation of daily 0h UTC IERS Rapid Service values."
      : "Tabular 0h UTC value.",
  };
}

function offsetAt(utc: Utc, allowExpired: boolean): number {
  requireCoverage(utc, allowExpired);
  let chosen: number | null = null;
  for (const bound of bounds) {
    if (compareUtc(bound.utc, utc) <= 0) chosen = bound.offset;
    else break;
  }
  if (chosen === null) throw new DataCoverageError("Before the leap-second table.");
  return chosen;
}

function offsetDuringLeap(utc: Utc, allowExpired: boolean): number {
  return offsetAt({ ...utc, hour: 23, minute: 59, second: 59, nanosecond: 0 }, allowExpired);
}

function isLeapLabel(utc: Utc, allowExpired: boolean): boolean {
  if (!(utc.hour === 23 && utc.minute === 59 && utc.second === 60)) return false;
  const old = offsetDuringLeap(utc, allowExpired);
  const next = shiftDays(utc, 1);
  try {
    return offsetAt({ ...next, hour: 0, minute: 0, second: 0, nanosecond: 0 }, allowExpired) === old + 1;
  } catch {
    return false;
  }
}

function requireCoverage(utc: Utc, allowExpired: boolean) {
  if (compareUtc(utc, bounds[0].utc) < 0) {
    throw new DataCoverageError("UTC before 1972-01-01 is not implemented.");
  }
  if (!allowExpired && compareUtc(utc, expiry) >= 0) {
    throw new LeapTableExpired(`Leap-second table expires at ${LEAP_EXPIRES}.`);
  }
}

function compareUtc(a: Utc, b: Utc): number {
  const delta = posixLike(a) - posixLike(b);
  if (delta !== 0n) return delta > 0n ? 1 : -1;
  return a.nanosecond - b.nanosecond;
}

function posixLike(utc: Utc): bigint {
  const days = BigInt(daysBetween(1972, 1, 1, utc.year, utc.month, utc.day));
  return days * 86_400n + BigInt(utc.hour * 3600 + utc.minute * 60 + utc.second);
}

function fromPosix(seconds: bigint, nanosecond: number): Utc {
  const days = seconds / 86_400n;
  let rem = Number(seconds % 86_400n);
  const hour = Math.floor(rem / 3600);
  rem -= hour * 3600;
  const minute = Math.floor(rem / 60);
  const second = rem - minute * 60;
  const [year, month, day] = civilFromDays(daysFromCivil(1972, 1, 1) + Number(days));
  return { year, month, day, hour, minute, second, nanosecond };
}

function shiftDays(utc: Utc, days: number): Utc {
  const [year, month, day] = civilFromDays(daysFromCivil(utc.year, utc.month, utc.day) + days);
  return { year, month, day, hour: 0, minute: 0, second: 0, nanosecond: 0 };
}

function validDate(year: number, month: number, day: number): boolean {
  const [y, m, d] = civilFromDays(daysFromCivil(year, month, day));
  return y === year && m === month && d === day;
}

export function daysFromCivil(year: number, month: number, day: number): number {
  let y = year;
  const m = month;
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor((y >= 0 ? y : y - 399) / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

function daysBetween(y0: number, m0: number, d0: number, y1: number, m1: number, d1: number): number {
  return daysFromCivil(y1, m1, d1) - daysFromCivil(y0, m0, d0);
}

function civilFromDays(z: number): [number, number, number] {
  let index = z + 719468;
  const era = Math.floor((index >= 0 ? index : index - 146096) / 146097);
  const doe = index - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  let y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  y += m <= 2 ? 1 : 0;
  return [y, m, d];
}

function wrap360(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

function mod24(hours: number): number {
  return ((hours % 24) + 24) % 24;
}
