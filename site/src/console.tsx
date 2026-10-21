import { useMemo, useState, type ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AU_M,
  C_M_S,
  COVERAGE,
  EARTH_RADIUS_M,
  MARS_RADIUS_M,
  MEAN_SOL_DAYS,
  addNanoseconds,
  accumulatedErrorSeconds,
  formatUtc,
  julianDateTt,
  lightTimeSeconds,
  localSolarTime,
  NS,
  parseUtc,
  referenceChecks,
  schwarzschildRate,
  srRate,
  taiMinusUtcSeconds,
  ttNanoseconds,
  twoWaySync,
  utcToTaiNs,
  ut1MinusUtc,
  weakFieldRate,
} from "./engine";

type Section = "scales" | "mars" | "rates" | "sync" | "limits";

const SECTIONS: { id: Section; index: string; label: string }[] = [
  { id: "scales", index: "01", label: "Scales" },
  { id: "mars", index: "02", label: "Mars" },
  { id: "rates", index: "03", label: "Rates" },
  { id: "sync", index: "04", label: "Sync" },
  { id: "limits", index: "05", label: "Limits" },
];

export function Console() {
  const [section, setSection] = useState<Section>("scales");
  const [utcText, setUtcText] = useState("2016-12-31T23:59:59Z");
  const [longitude, setLongitude] = useState("175.47");
  const [positive, setPositive] = useState<"east" | "west">("east");
  const [model, setModel] = useState<"sr" | "schwarzschild" | "weak">("sr");
  const [speed, setSpeed] = useState("7800");
  const [radius, setRadius] = useState(String(EARTH_RADIUS_M));
  const [span, setSpan] = useState("86400");
  const [delayAb, setDelayAb] = useState("499.004783836");
  const [delayBa, setDelayBa] = useState("499.204783836");
  const [offsetB, setOffsetB] = useState("0");
  const [yB, setYB] = useState("1e-12");
  const checks = useMemo(() => referenceChecks(), []);
  const passed = checks.filter((item) => item.passed).length;

  return (
    <main className="min-h-screen bg-paper text-ink">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 sm:px-8 sm:py-8">
          <div className="flex items-baseline justify-between gap-4">
            <p className="font-mono text-xs tracking-[0.18em] text-oxide uppercase">Chronos</p>
            <p className="font-mono text-xs text-muted">
              {passed}/{checks.length} published checks
            </p>
          </div>
          <div className="max-w-3xl">
            <h1 className="text-3xl leading-tight font-medium tracking-tight sm:text-4xl">
              Timekeeping for more than one planet
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-muted">
              TAI, UTC with leap seconds, Terrestrial Time, a dated UT1 snapshot, and the NASA
              Mars24 mean solar convention. Relativistic rates stay inside the model that derived
              them. What cannot be validated is refused.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-px overflow-hidden border border-rule bg-rule sm:grid-cols-4">
            <Fact label="TAI − UTC" value="37 s" note="since 2017-01-01" />
            <Fact label="Leap table" value="2027-06-28" note="IERS expiry" />
            <Fact label="UT1 window" value={COVERAGE.ut1First.slice(2)} note={`through ${COVERAGE.ut1Last}`} />
            <Fact label="Mean sol" value="88 775.244 s" note="Mars24 divisor" />
          </dl>
        </div>
      </header>

      <nav className="sticky top-0 z-10 border-b border-rule bg-paper/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 sm:px-8">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSection(item.id)}
              className={`flex min-h-11 shrink-0 items-baseline gap-2 border-b-2 px-3 py-3 font-mono text-sm ${
                section === item.id ? "border-oxide text-ink" : "border-transparent text-muted"
              }`}
            >
              <span className="text-oxide">{item.index}</span>
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-6 sm:px-8 sm:py-8 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        {section === "scales" && (
          <Scales utcText={utcText} setUtcText={setUtcText} />
        )}
        {section === "mars" && (
          <Mars
            utcText={utcText}
            setUtcText={setUtcText}
            longitude={longitude}
            setLongitude={setLongitude}
            positive={positive}
            setPositive={setPositive}
          />
        )}
        {section === "rates" && (
          <Rates
            model={model}
            setModel={setModel}
            speed={speed}
            setSpeed={setSpeed}
            radius={radius}
            setRadius={setRadius}
            span={span}
            setSpan={setSpan}
          />
        )}
        {section === "sync" && (
          <Sync
            delayAb={delayAb}
            setDelayAb={setDelayAb}
            delayBa={delayBa}
            setDelayBa={setDelayBa}
            offsetB={offsetB}
            setOffsetB={setOffsetB}
            yB={yB}
            setYB={setYB}
          />
        )}
        {section === "limits" && <Limits utcText={utcText} setUtcText={setUtcText} />}
      </div>
    </main>
  );
}

function Scales({
  utcText,
  setUtcText,
}: {
  utcText: string;
  setUtcText: (value: string) => void;
}) {
  const sheet = useMemo(() => readScales(utcText), [utcText]);
  return (
    <>
      <Controls title="UTC label" hint="Z only. Second 60 is legal on a real leap second.">
        <Field label="Instant" value={utcText} onChange={setUtcText} mono />
        <div className="flex flex-wrap gap-2">
          <Mini onClick={() => step(utcText, setUtcText, -1n)} label="−1 s" />
          <Mini onClick={() => step(utcText, setUtcText, 1n)} label="+1 s" />
          <Mini onClick={() => setUtcText("2016-12-31T23:59:59Z")} label="Leap eve" />
          <Mini onClick={() => setUtcText("2000-01-06T00:00:00Z")} label="Mars24" />
          <Mini onClick={() => setUtcText("2026-10-20T00:00:00Z")} label="UT1 obs." />
        </div>
      </Controls>
      <Ledger
        kicker="Continuous count goes through TAI"
        equation={"TT = TAI + 32.184 s\nUTC = TAI − (leap seconds)"}
        rows={sheet.rows}
        error={sheet.error}
        note="A Unix timestamp cannot represent 23:59:60. Adding one second steps through TAI, so the leap label appears as its own second."
      />
    </>
  );
}

function Mars(props: {
  utcText: string;
  setUtcText: (value: string) => void;
  longitude: string;
  setLongitude: (value: string) => void;
  positive: "east" | "west";
  setPositive: (value: "east" | "west") => void;
}) {
  const sheet = useMemo(
    () => readMars(props.utcText, props.longitude, props.positive),
    [props.utcText, props.longitude, props.positive],
  );
  return (
    <>
      <Controls title="Mean solar convention" hint="Mars24 is a function of TT, not a clock on Mars.">
        <Field label="UTC instant" value={props.utcText} onChange={props.setUtcText} mono />
        <Field label="Longitude (degrees)" value={props.longitude} onChange={props.setLongitude} mono />
        <div className="flex gap-2">
          <Mini onClick={() => props.setPositive("east")} label="East +" active={props.positive === "east"} />
          <Mini onClick={() => props.setPositive("west")} label="West +" active={props.positive === "west"} />
        </div>
        <p className="text-sm leading-relaxed text-muted">
          Mars24 uses west-positive planetographic longitude. The IAU planetocentric convention is
          east-positive. The sign is selected, not assumed.
        </p>
      </Controls>
      <Ledger
        kicker="Not a civil Martian timestamp"
        equation="MSD = (JD_TT − 2451549.5) / 1.0274912517 + 44796 − 0.0009626"
        rows={sheet.rows}
        error={sheet.error}
        note="One mean sol is 1.0274912517 Earth days of 86400 s, which rounds to 88775.244 s. The sidereal rotation is 88642.663 s. Local true solar time adds an equation of time that can exceed 40 minutes."
      />
    </>
  );
}

function Rates(props: {
  model: "sr" | "schwarzschild" | "weak";
  setModel: (value: "sr" | "schwarzschild" | "weak") => void;
  speed: string;
  setSpeed: (value: string) => void;
  radius: string;
  setRadius: (value: string) => void;
  span: string;
  setSpan: (value: string) => void;
}) {
  const sheet = useMemo(
    () => readRates(props.model, props.speed, props.radius, props.span),
    [props.model, props.speed, props.radius, props.span],
  );
  const curve = useMemo(() => srCurve(), []);
  return (
    <>
      <Controls title="Clock rate" hint="Three models. They are not multiplied together.">
        <div className="flex flex-col gap-2">
          <Mini onClick={() => props.setModel("sr")} label="Inertial SR" active={props.model === "sr"} />
          <Mini
            onClick={() => props.setModel("schwarzschild")}
            label="Schwarzschild, at rest"
            active={props.model === "schwarzschild"}
          />
          <Mini
            onClick={() => props.setModel("weak")}
            label="Weak field, √metric"
            active={props.model === "weak"}
          />
        </div>
        <Field label="Speed (m/s)" value={props.speed} onChange={props.setSpeed} mono />
        <Field label="Radius (m)" value={props.radius} onChange={props.setRadius} mono />
        <Field label="Coordinate interval (s)" value={props.span} onChange={props.setSpan} mono />
        <div className="flex flex-wrap gap-2">
          <Mini onClick={() => props.setRadius(String(EARTH_RADIUS_M))} label="Earth a" />
          <Mini onClick={() => props.setRadius(String(MARS_RADIUS_M))} label="Mars R" />
          <Mini onClick={() => props.setSpeed("0")} label="v = 0" />
          <Mini onClick={() => props.setSpeed(String(0.6 * C_M_S))} label="0.6 c" />
        </div>
      </Controls>
      <div className="flex min-w-0 flex-col gap-6">
        <Ledger
          kicker={sheet.kicker}
          equation={sheet.equation}
          rows={sheet.rows}
          error={sheet.error}
          note={sheet.note}
        />
        <figure className="border border-rule bg-panel p-4">
          <figcaption className="mb-3 font-mono text-xs tracking-wide text-muted uppercase">
            Special-relativistic deficit over 86 400 s. No gravity.
          </figcaption>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curve}>
                <XAxis dataKey="label" tick={{ fill: "#6e675e", fontSize: 11 }} stroke="#ddd6c8" />
                <YAxis
                  tick={{ fill: "#6e675e", fontSize: 11 }}
                  stroke="#ddd6c8"
                  tickFormatter={(value: number) => value.toExponential(0)}
                />
                <Tooltip
                  contentStyle={{ background: "#fffdf8", border: "1px solid #ddd6c8", fontSize: 12 }}
                  formatter={(value) => [typeof value === "number" ? value.toExponential(3) : value, "τ − t (s)"]}
                />
                <Line dataKey="deficit" stroke="#8c3b22" strokeWidth={1.6} dot={{ r: 3, fill: "#8c3b22" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </figure>
      </div>
    </>
  );
}

function Sync(props: {
  delayAb: string;
  setDelayAb: (value: string) => void;
  delayBa: string;
  setDelayBa: (value: string) => void;
  offsetB: string;
  setOffsetB: (value: string) => void;
  yB: string;
  setYB: (value: string) => void;
}) {
  const sheet = useMemo(
    () => readSync(props.delayAb, props.delayBa, props.offsetB, props.yB),
    [props.delayAb, props.delayBa, props.offsetB, props.yB],
  );
  return (
    <>
      <Controls title="Two-way exchange" hint="The estimate assumes the path delay is symmetric.">
        <Field label="Delay A → B (s)" value={props.delayAb} onChange={props.setDelayAb} mono />
        <Field label="Delay B → A (s)" value={props.delayBa} onChange={props.setDelayBa} mono />
        <Field label="True offset of B (s)" value={props.offsetB} onChange={props.setOffsetB} mono />
        <Field label="Frequency offset y of B" value={props.yB} onChange={props.setYB} mono />
        <div className="flex flex-wrap gap-2">
          <Mini
            onClick={() => {
              props.setDelayAb(String(lightTimeSeconds(AU_M)));
              props.setDelayBa(String(lightTimeSeconds(AU_M)));
            }}
            label="Symmetric 1 AU"
          />
          <Mini
            onClick={() => {
              const one = lightTimeSeconds(AU_M);
              props.setDelayAb(String(one));
              props.setDelayBa(String(one + 0.2));
            }}
            label="+0.2 s asymmetry"
          />
        </div>
      </Controls>
      <div className="flex min-w-0 flex-col gap-6">
        <Ledger
          kicker="A better clock does not measure the path"
          equation="offset ≈ ((τ2−τ1) + (τ3−τ4)) / 2"
          rows={sheet.rows}
          error={sheet.error}
          note="With zero frequency offset, the synchronization error equals half the delay asymmetry. A fractional frequency offset is a different error: it is invisible at the first epoch and then grows as y × t."
        />
        {!sheet.error && (
          <figure className="border border-rule bg-panel p-4">
            <figcaption className="mb-3 font-mono text-xs tracking-wide text-muted uppercase">
              True offset grows with y. One exchange’s error does not.
            </figcaption>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sheet.curve}>
                  <XAxis dataKey="day" tick={{ fill: "#6e675e", fontSize: 11 }} stroke="#ddd6c8" />
                  <YAxis tick={{ fill: "#6e675e", fontSize: 11 }} stroke="#ddd6c8" />
                  <Tooltip
                    contentStyle={{ background: "#fffdf8", border: "1px solid #ddd6c8", fontSize: 12 }}
                  />
                  <Line dataKey="offset" name="|true offset| (s)" stroke="#8c3b22" strokeWidth={1.6} dot={false} />
                  <Line dataKey="error" name="|sync error| (s)" stroke="#1b1916" strokeWidth={1.6} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </figure>
        )}
      </div>
    </>
  );
}

function Limits({
  utcText,
  setUtcText,
}: {
  utcText: string;
  setUtcText: (value: string) => void;
}) {
  const probes = [
    ["Before 1972", "1965-01-01T00:00:00Z"],
    ["After leap expiry", "2027-06-28T00:00:00Z"],
    ["Invented leap", "2018-12-31T23:59:60Z"],
    ["Zone offset", "2026-10-21T06:12:00+05:30"],
  ] as const;
  return (
    <>
      <Controls title="What this will not answer" hint="Each probe is evaluated. A refusal is the result.">
        {probes.map(([label, value]) => (
          <Mini key={value} onClick={() => setUtcText(value)} label={label} active={utcText === value} />
        ))}
      </Controls>
      <div className="flex min-w-0 flex-col gap-4">
        <Ledger
          kicker="Unsupported on purpose"
          equation="TDB and a Mars-surface proper time need an ephemeris this instrument does not carry."
          rows={refusalRows(utcText)}
          error={null}
          note="TDB is defined from TCB by an IAU rate, and TCB − TCG needs the geocenter's barycentric state. A two-term sine is not returned in its place. A clock on Mars is not the Mars24 function of TT."
        />
        <ul className="grid gap-3 text-sm leading-relaxed text-muted">
          <li className="border-t border-rule pt-3">
            Established: the SI second, TT − TAI = 32.184 s, and the integer leap-second table since 1972.
          </li>
          <li className="border-t border-rule pt-3">
            Convention: Mars Sol Date and Airy mean solar time, Mars24 / Allison & McEwen.
          </li>
          <li className="border-t border-rule pt-3">
            Approximation: daily linear UT1−UTC, and the spherical weak-field metric inside its stated domain.
          </li>
          <li className="border-t border-rule pt-3">
            Not claimed: navigation, GNSS, geoid time, or a prediction of any physical clock.
          </li>
        </ul>
      </div>
    </>
  );
}

function Controls({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">{title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">{hint}</p>
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  mono,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  mono?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="text-muted">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`min-h-11 border border-rule bg-panel px-3 text-ink outline-none focus:border-oxide ${
          mono ? "font-mono text-sm" : ""
        }`}
        spellCheck={false}
      />
    </label>
  );
}

function Mini({
  label,
  onClick,
  active,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-11 border px-3 text-left text-sm ${
        active ? "border-oxide bg-oxide text-panel" : "border-rule bg-panel text-ink"
      }`}
    >
      {label}
    </button>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="bg-paper px-3 py-3">
      <dt className="font-mono text-xs tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-1 font-mono text-sm text-ink">{value}</dd>
      <dd className="text-xs text-muted">{note}</dd>
    </div>
  );
}

type Row = { label: string; value: string; unit: string };

function Ledger({
  kicker,
  equation,
  rows,
  error,
  note,
}: {
  kicker: string;
  equation: string;
  rows: Row[];
  error: string | null;
  note: string;
}) {
  return (
    <section className="min-w-0 border border-rule bg-panel">
      <div className="border-b border-rule px-4 py-3">
        <p className="font-mono text-xs tracking-wide text-oxide uppercase">{kicker}</p>
        <p className="mt-2 font-mono text-sm leading-relaxed whitespace-pre-line text-ink">{equation}</p>
      </div>
      {error ? (
        <p className="px-4 py-5 text-sm leading-relaxed text-oxide">{error}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-rule last:border-0">
                <th className="w-[34%] px-4 py-3 font-normal text-muted">{row.label}</th>
                <td className="px-2 py-3">
                  <div className="font-mono break-all text-ink">{row.value}</div>
                  <div className="mt-1 text-xs text-muted sm:hidden">{row.unit}</div>
                </td>
                <td className="hidden px-4 py-3 text-right text-muted sm:table-cell">{row.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="border-t border-rule px-4 py-3 text-sm leading-relaxed text-muted">{note}</p>
    </section>
  );
}

function step(text: string, setUtcText: (value: string) => void, delta: bigint) {
  try {
    setUtcText(formatUtc(addNanoseconds(parseUtc(text), delta * NS)));
  } catch {
    /* the ledger already explains the bad label */
  }
}

function readScales(text: string): { rows: Row[]; error: string | null } {
  try {
    const utc = parseUtc(text);
    const tai = utcToTaiNs(utc);
    const tt = ttNanoseconds(tai);
    const rows: Row[] = [
      { label: "UTC", value: formatUtc(utc), unit: "calendar label" },
      { label: "TAI − UTC", value: String(taiMinusUtcSeconds(utc)), unit: "s" },
      { label: "TAI", value: tai.toString(), unit: "ns since 1972-01-01 TAI" },
      { label: "TT", value: tt.toString(), unit: "ns since 1972-01-01 TT" },
      { label: "Julian Date TT", value: julianDateTt(tt).toFixed(8), unit: "JD" },
    ];
    try {
      const ut1 = ut1MinusUtc(utc);
      rows.push({
        label: "UT1 − UTC",
        value: `${ut1.seconds.toFixed(7)}${ut1.prediction ? "  (prediction)" : ""}`,
        unit: "s",
      });
    } catch (error) {
      rows.push({
        label: "UT1 − UTC",
        value: error instanceof Error ? error.message : "unavailable",
        unit: "not in snapshot",
      });
    }
    return { rows, error: null };
  } catch (error) {
    return { rows: [], error: message(error) };
  }
}

function readMars(text: string, longitude: string, positive: "east" | "west"): { rows: Row[]; error: string | null } {
  try {
    const utc = parseUtc(text);
    const tt = ttNanoseconds(utcToTaiNs(utc));
    const lon = Number(longitude);
    if (!Number.isFinite(lon)) throw new Error("Longitude must be a finite number of degrees.");
    const local = localSolarTime(tt, lon, positive);
    const state = local.state;
    const solRatio = (1 / MEAN_SOL_DAYS).toFixed(10);
    return {
      error: null,
      rows: [
        { label: "Mars Sol Date", value: state.marsSolDate.toFixed(6), unit: "sols since convention epoch" },
        { label: "Airy mean solar time", value: clockFromHours(state.meanSolarHours), unit: "MTC, hours" },
        { label: "Local mean solar time", value: clockFromHours(local.localMeanHours), unit: `${positive}-positive longitude` },
        { label: "Local true solar time", value: clockFromHours(local.localTrueHours), unit: "mean + equation of time" },
        { label: "Solar longitude Ls", value: state.solarLongitudeDeg.toFixed(5), unit: "degrees" },
        { label: "Equation of time", value: state.equationOfTimeHours.toFixed(5), unit: "hours" },
        { label: "Sols per 86400 s", value: solRatio, unit: "mean sols" },
      ],
    };
  } catch (error) {
    return { rows: [], error: message(error) };
  }
}

function readRates(model: "sr" | "schwarzschild" | "weak", speedText: string, radiusText: string, spanText: string) {
  const equations = {
    sr: "dτ/dt = √((1−β)(1+β))",
    schwarzschild: "dτ/dt = √(1 − r_s/r),  clock at rest",
    weak: "(dτ/dt)² = 1 + 2Φ/c² − (1 − 2Φ/c²) v²/c²",
  };
  const notes = {
    sr: "Inertial coordinate time. No gravitational field. 0.6c is a speed, not an orbit.",
    schwarzschild: "Schwarzschild coordinate time, not TT. Spherical, non-rotating mass. Earth's J2 is omitted and is tens of nanoseconds per day.",
    weak: "Taken from the stated metric. Refused when |Φ|/c² > 10⁻⁵ or v/c > 0.01. Not a GNSS model.",
  };
  try {
    const speed = Number(speedText);
    const radius = Number(radiusText);
    const span = Number(spanText);
    if (!Number.isFinite(span) || span < 0) throw new Error("Coordinate interval must be ≥ 0 seconds.");
    let rate: number;
    if (model === "sr") rate = srRate(speed);
    else if (model === "schwarzschild") {
      if (speed !== 0) throw new Error("The stationary Schwarzschild model requires speed 0. Use the weak-field model for slow motion.");
      rate = schwarzschildRate(radius);
    } else rate = weakFieldRate(radius, speed);
    const deficit = span * (rate - 1);
    return {
      kicker: model === "sr" ? "Proper time, constant velocity" : "Gravitational model, bounded",
      equation: equations[model],
      note: notes[model],
      error: null,
      rows: [
        { label: "dτ/dt", value: rate.toPrecision(12), unit: "dimensionless" },
        { label: "Coordinate interval", value: String(span), unit: "s of this model's t" },
        { label: "Proper − coordinate", value: deficit.toExponential(6), unit: "s" },
        { label: "Speed", value: String(speed), unit: "m/s" },
        { label: "Radius", value: String(radius), unit: "m" },
      ],
    };
  } catch (error) {
    return { kicker: "Refused", equation: equations[model], note: notes[model], rows: [], error: message(error) };
  }
}

function readSync(delayAb: string, delayBa: string, offsetB: string, yB: string) {
  try {
    const input = {
      delayAbS: num(delayAb, "Delay A to B"),
      delayBaS: num(delayBa, "Delay B to A"),
      offsetBS: num(offsetB, "Offset"),
      yB: num(yB, "Frequency offset"),
      yA: 0,
      sendS: 0,
    };
    const now = twoWaySync(input);
    const curve = [0, 30, 180, 365].map((day) => {
      const later = twoWaySync({ ...input, sendS: day * 86400 });
      return { day, error: Math.abs(later.errorS), offset: Math.abs(later.trueOffsetS) };
    });
    const driftYear = accumulatedErrorSeconds(input.yB, 365.25 * 86400);
    return {
      error: null,
      curve,
      rows: [
        { label: "True offset", value: now.trueOffsetS.toExponential(6), unit: "s at send epoch" },
        { label: "Estimated offset", value: now.estimatedOffsetS.toExponential(6), unit: "s" },
        { label: "Synchronization error", value: now.errorS.toExponential(6), unit: "s" },
        { label: "Half the asymmetry", value: now.asymmetryBiasS.toExponential(6), unit: "s" },
        { label: "Round trip", value: now.roundTripS.toFixed(6), unit: "s" },
        { label: "y × 365.25 days", value: driftYear.toExponential(6), unit: "s, frequency term only" },
      ],
    };
  } catch (error) {
    return { error: message(error), rows: [] as Row[], curve: [] as { day: number; error: number; offset: number }[] };
  }
}

function refusalRows(text: string): Row[] {
  let evaluated = "not evaluated";
  try {
    parseUtc(text);
    utcToTaiNs(parseUtc(text));
    evaluated = formatUtc(parseUtc(text));
  } catch (error) {
    evaluated = message(error);
  }
  let luminal = "not rejected";
  try {
    srRate(C_M_S);
  } catch (error) {
    luminal = message(error);
  }
  return [
    { label: "This UTC label", value: evaluated, unit: text },
    { label: "Speed = c", value: luminal, unit: "m/s" },
    { label: "TDB", value: "Unsupported. Needs a planetary ephemeris.", unit: "not computed" },
    { label: "Mars proper time", value: "Unsupported. Mars24 is not that reduction.", unit: "not computed" },
  ];
}

function srCurve() {
  return [
    { label: "0", speed: 0 },
    { label: "3 km/s", speed: 3000 },
    { label: "7.8", speed: 7800 },
    { label: "30 km/s", speed: 29780 },
    { label: "0.1c", speed: 0.1 * C_M_S },
  ].map((item) => ({
    label: item.label,
    deficit: 86400 * (srRate(item.speed) - 1),
  }));
}

function clockFromHours(hours: number): string {
  const wrapped = ((hours % 24) + 24) % 24;
  let h = Math.floor(wrapped);
  let m = Math.floor((wrapped - h) * 60);
  let s = Math.round(((wrapped - h) * 60 - m) * 60);
  if (s === 60) {
    s = 0;
    m += 1;
  }
  if (m === 60) {
    m = 0;
    h = (h + 1) % 24;
  }
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function num(text: string, label: string): number {
  const value = Number(text);
  if (!Number.isFinite(value)) throw new Error(`${label} must be a finite number.`);
  return value;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The value could not be evaluated.";
}
