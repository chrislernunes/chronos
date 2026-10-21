import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  AU_M,
  C_M_S,
  EARTH_GM,
  EARTH_RADIUS_M,
  InvalidInput,
  InvalidLeapSecond,
  LeapTableExpired,
  DataCoverageError,
  MARS_GM,
  MARS_RADIUS_M,
  formatUtc,
  julianDateTt,
  lightTimeNanoseconds,
  localSolarTime,
  marsSolarState,
  parseUtc,
  referenceChecks,
  schwarzschildRate,
  srRate,
  taiMinusUtcSeconds,
  taiToUtc,
  ttNanoseconds,
  twoWaySync,
  unsupported,
  utcToTaiNs,
  ut1MinusUtc,
  weakFieldRate,
} from "./engine.ts";

type Fixture = {
  utc: { input: string; offset: number; tai: string; tt: string; back: string; jd: string }[];
  rejections: { input: string; error: string }[];
  ut1: { input: string; seconds: string; sigma: string; prediction: boolean }[];
  ut1Rejections: string[];
  mars: {
    input: string;
    longitude: number;
    positive: "east" | "west";
    msd: string;
    mst: number;
    ls: number;
    eot: number;
    meanAnomaly: number;
    lmst: number;
    ltst: number;
    jd: string;
  }[];
  rates: Record<string, string>;
  lightAuNs: string;
  syncNs: { estimated: string; error: string; bias: string };
};

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../tests/fixtures/browser_parity.json", import.meta.url)), "utf8"),
) as Fixture;

const rejectionTypes: Record<string, new (...args: never[]) => Error> = {
  DataCoverageError,
  LeapTableExpired,
  InvalidLeapSecond,
  InvalidInput,
};

test("published checks inside the page all pass", () => {
  const failed = referenceChecks().filter((item) => !item.passed);
  assert.deepEqual(failed, []);
});

test("UTC, TAI and TT match the Python integers", () => {
  for (const row of fixture.utc) {
    const utc = parseUtc(row.input);
    const tai = utcToTaiNs(utc);
    const tt = ttNanoseconds(tai);
    assert.equal(taiMinusUtcSeconds(utc), row.offset, row.input);
    assert.equal(tai.toString(), row.tai, row.input);
    assert.equal(tt.toString(), row.tt, row.input);
    assert.equal(formatUtc(taiToUtc(tai)), row.back, row.input);
    assert.ok(Math.abs(julianDateTt(tt) - Number(row.jd)) < 1e-9, row.input);
  }
});

test("out of coverage and invalid labels are refused", () => {
  for (const row of fixture.rejections) {
    assert.throws(() => utcToTaiNs(parseUtc(row.input)), rejectionTypes[row.error], row.input);
  }
  for (const text of fixture.ut1Rejections) {
    assert.throws(() => ut1MinusUtc(parseUtc(text)), text);
  }
  assert.throws(() => srRate(-1), InvalidInput);
  assert.throws(() => srRate(C_M_S), InvalidInput);
  assert.throws(() => schwarzschildRate(0.001, EARTH_GM), InvalidInput);
  assert.throws(() => weakFieldRate(EARTH_RADIUS_M, 0.2 * C_M_S, EARTH_GM), InvalidInput);
  assert.throws(() => unsupported("tdb"));
  assert.throws(() => unsupported("mars-proper-time"));
});

test("UT1 snapshot matches the Python daily values", () => {
  for (const row of fixture.ut1) {
    const got = ut1MinusUtc(parseUtc(row.input));
    assert.ok(Math.abs(got.seconds - Number(row.seconds)) < 1e-12, row.input);
    assert.ok(Math.abs(got.sigma - Number(row.sigma)) < 1e-12, row.input);
    assert.equal(got.prediction, row.prediction, row.input);
  }
});

test("Mars24 agrees with the Python series inside float tolerance", () => {
  for (const row of fixture.mars) {
    const tt = ttNanoseconds(utcToTaiNs(parseUtc(row.input)));
    const state = marsSolarState(tt);
    const local = localSolarTime(tt, row.longitude, row.positive);
    assert.ok(Math.abs(state.julianDateTt - Number(row.jd)) < 1e-9, row.input);
    assert.ok(Math.abs(state.marsSolDate - Number(row.msd)) < 1e-6, row.input);
    assert.ok(Math.abs(state.meanSolarHours - row.mst) < 1e-8, row.input);
    assert.ok(Math.abs(state.solarLongitudeDeg - row.ls) < 1e-8, row.input);
    assert.ok(Math.abs(state.equationOfTimeHours - row.eot) < 1e-8, row.input);
    assert.ok(Math.abs(state.meanAnomalyDeg - row.meanAnomaly) < 1e-8, row.input);
    assert.ok(Math.abs(local.localMeanHours - row.lmst) < 1e-8, row.input);
    assert.ok(Math.abs(local.localTrueHours - row.ltst) < 1e-8, row.input);
  }
  const tt = ttNanoseconds(utcToTaiNs(parseUtc("2000-01-06T00:00:00Z")));
  const east = localSolarTime(tt, 15, "east");
  const west = localSolarTime(tt, 15, "west");
  assert.ok(Math.abs(((east.localMeanHours - west.localMeanHours) % 24 + 24) % 24 - 2) < 1e-9);
});

test("relativistic rates and one-AU light time", () => {
  const got = {
    sr0: srRate(0),
    sr06: srRate(0.6 * C_M_S),
    schEarth: schwarzschildRate(EARTH_RADIUS_M, EARTH_GM),
    weakEarth0: weakFieldRate(EARTH_RADIUS_M, 0, EARTH_GM),
    schMars: schwarzschildRate(MARS_RADIUS_M, MARS_GM),
    weakMars7800: weakFieldRate(MARS_RADIUS_M, 7800, MARS_GM),
    weakEarth7800: weakFieldRate(EARTH_RADIUS_M, 7800, EARTH_GM),
  };
  for (const [name, value] of Object.entries(got)) {
    const expected = Number(fixture.rates[name]);
    const scale = Math.max(1, Math.abs(expected));
    assert.ok(Math.abs(value - expected) / scale < 1e-12, `${name}: ${value} vs ${expected}`);
  }
  assert.equal(got.schEarth, got.weakEarth0);
  assert.equal(lightTimeNanoseconds(AU_M).toString(), fixture.lightAuNs);
  const sync = twoWaySync({ delayAbS: 10, delayBaS: 4, offsetBS: 5, yA: 0, yB: 0, sendS: 0 });
  assert.equal(String(Math.round(sync.estimatedOffsetS * 1e9)), fixture.syncNs.estimated);
  assert.equal(String(Math.round(sync.errorS * 1e9)), fixture.syncNs.error);
  assert.equal(String(Math.round(sync.asymmetryBiasS * 1e9)), fixture.syncNs.bias);
});
