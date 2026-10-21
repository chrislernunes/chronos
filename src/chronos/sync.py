"""Clock offset, constant frequency error, and two-way time transfer.

Terminology used in the results
-------------------------------
* Fractional frequency offset ``y``: indicated rate minus ideal rate, divided
  by the ideal rate. Constant in this model. Not an Allan deviation.
* Synchronization error: estimated clock offset minus the true offset at a
  stated epoch.
* Measurement noise: optional independent Gaussian noise on exchanged
  timestamps. It is synthetic. It is not a record of an atomic clock.
* The deterministic accumulation ``y × t`` is what this module calls frequency
  error. A random walk of frequency is not implemented.

The ideal time argument is a monotone coordinate labeled in SI nanoseconds.
For these experiments it may be read as TAI elapsed from an arbitrary origin.
The simulation does not create TAI and does not emit atomic-clock data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from chronos.core import Duration, InvalidInput
from chronos.precision import nanoseconds_from_seconds, scale_nanoseconds


@dataclass(frozen=True)
class Clock:
    """Affine clock: indicated = ideal + offset0 + y × (ideal − t0).

    ``fractional_frequency_offset`` is dimensionless. ``t0`` is the ideal
    instant at which ``initial_offset`` applies, as nanoseconds of ideal time.
    """

    name: str
    fractional_frequency_offset: Decimal
    initial_offset: Duration
    t0_nanoseconds: int = 0

    def indicated(self, ideal_nanoseconds: int) -> int:
        y = Decimal(self.fractional_frequency_offset)
        elapsed = ideal_nanoseconds - self.t0_nanoseconds
        # (1+y) × elapsed + offset, with y × elapsed rounded to 1 ns.
        stretched = elapsed + scale_nanoseconds(elapsed, y)
        return stretched + self.initial_offset.nanoseconds


@dataclass(frozen=True)
class GaussianTimestampNoise:
    """Independent N(0, σ²) noise added to each exchanged timestamp.

    σ is in seconds. The model is white in the phase samples. It has no
    flicker floor and no random-walk frequency. ``seed`` makes the draw
    reproducible. Samples are not atomic-clock measurements.
    """

    sigma_seconds: Decimal
    seed: int

    def generator(self) -> random.Random:
        if self.sigma_seconds < 0:
            raise InvalidInput("noise sigma must be ≥ 0")
        return random.Random(self.seed)

    def sample_nanoseconds(self, rng: random.Random) -> int:
        if self.sigma_seconds == 0:
            return 0
        draw = Decimal(str(rng.gauss(0.0, float(self.sigma_seconds))))
        # float64 is enough to draw the Gaussian; the clock arithmetic stays integral.
        return nanoseconds_from_seconds(draw)


@dataclass(frozen=True)
class TwoWayExchange:
    """One immediate-turnaround two-way exchange, in indicated nanoseconds."""

    tau1_ns: int
    tau2_ns: int
    tau3_ns: int
    tau4_ns: int
    ideal_send_ns: int
    delay_ab: Duration
    delay_ba: Duration

    @property
    def estimated_offset_b_minus_a(self) -> Duration:
        """NTP-style offset, assuming the path delay is symmetric."""

        # ((τ2−τ1) + (τ3−τ4)) / 2
        numerator = (self.tau2_ns - self.tau1_ns) + (self.tau3_ns - self.tau4_ns)
        # Integer division would bias odd numerators. The numerator is even
        # when all timestamps are integral and delays are integral, but noise
        # can make it odd. Round half away from zero toward the nearer ns via
        # explicit even check: use half-up on the absolute value.
        return Duration(_div_round_nearest(numerator, 2))

    @property
    def estimated_round_trip(self) -> Duration:
        """(τ4−τ1) − (τ3−τ2), the estimated two-way delay."""

        return Duration((self.tau4_ns - self.tau1_ns) - (self.tau3_ns - self.tau2_ns))


@dataclass(frozen=True)
class SyncAssessment:
    exchange: TwoWayExchange
    true_offset_b_minus_a: Duration
    estimated_offset_b_minus_a: Duration
    synchronization_error: Duration
    delay_asymmetry: Duration
    analytic_asymmetry_bias: Duration
    frequency_offsets: tuple[Decimal, Decimal]
    note: str


def accumulated_time_error(clock: Clock, ideal_elapsed: Duration) -> Duration:
    """Indicated elapsed minus ideal elapsed, from the clock's t0.

    For a constant ``y`` this is the rounded value of ``y × elapsed`` plus any
    initial offset already present at t0. Passing a clock whose initial offset
    is zero isolates the frequency contribution.
    """

    if clock.initial_offset.nanoseconds != 0:
        raise InvalidInput(
            "accumulated_time_error requires a zero initial offset so the "
            "result is the frequency contribution. Read clock.indicated for the sum."
        )
    indicated_elapsed = clock.indicated(clock.t0_nanoseconds + ideal_elapsed.nanoseconds) - clock.indicated(
        clock.t0_nanoseconds
    )
    return Duration(indicated_elapsed - ideal_elapsed.nanoseconds)


def two_way_exchange(
    clock_a: Clock,
    clock_b: Clock,
    *,
    ideal_send_nanoseconds: int,
    delay_ab: Duration,
    delay_ba: Duration,
    noise: GaussianTimestampNoise | None = None,
) -> TwoWayExchange:
    """Immediate server turnaround. Processing delay is zero ideal seconds.

    Ideal schedule:
    * A transmits at ``t1``.
    * B receives at ``t1 + delay_ab``.
    * B transmits at that same ideal instant.
    * A receives at ``t1 + delay_ab + delay_ba``.
    """

    if delay_ab.nanoseconds < 0 or delay_ba.nanoseconds < 0:
        raise InvalidInput("signal delays must be ≥ 0")
    t1 = ideal_send_nanoseconds
    t2 = t1 + delay_ab.nanoseconds
    t3 = t2
    t4 = t3 + delay_ba.nanoseconds
    tau1 = clock_a.indicated(t1)
    tau2 = clock_b.indicated(t2)
    tau3 = clock_b.indicated(t3)
    tau4 = clock_a.indicated(t4)
    if noise is not None:
        rng = noise.generator()
        tau1 += noise.sample_nanoseconds(rng)
        tau2 += noise.sample_nanoseconds(rng)
        tau3 += noise.sample_nanoseconds(rng)
        tau4 += noise.sample_nanoseconds(rng)
    return TwoWayExchange(
        tau1_ns=tau1,
        tau2_ns=tau2,
        tau3_ns=tau3,
        tau4_ns=tau4,
        ideal_send_ns=t1,
        delay_ab=delay_ab,
        delay_ba=delay_ba,
    )


def assess_exchange(clock_a: Clock, clock_b: Clock, exchange: TwoWayExchange) -> SyncAssessment:
    """Compare the symmetric-delay estimate with the true offset at transmit time.

    With constant offsets and ``y = 0``, the estimate equals the true offset
    plus half the delay asymmetry ``(delay_ab − delay_ba) / 2``. A better
    frequency does not remove that bias. Nonzero ``y`` makes the true offset
    time-dependent; the reference used here is ``indicated_B − indicated_A``
    at the ideal transmit instant, before noise.
    """

    true = Duration(clock_b.indicated(exchange.ideal_send_ns) - clock_a.indicated(exchange.ideal_send_ns))
    estimated = exchange.estimated_offset_b_minus_a
    asymmetry = Duration(exchange.delay_ab.nanoseconds - exchange.delay_ba.nanoseconds)
    bias = Duration(_div_round_nearest(asymmetry.nanoseconds, 2))
    return SyncAssessment(
        exchange=exchange,
        true_offset_b_minus_a=true,
        estimated_offset_b_minus_a=estimated,
        synchronization_error=Duration(estimated.nanoseconds - true.nanoseconds),
        delay_asymmetry=asymmetry,
        analytic_asymmetry_bias=bias,
        frequency_offsets=(clock_a.fractional_frequency_offset, clock_b.fractional_frequency_offset),
        note=(
            "Symmetric-delay two-way estimate. Delay asymmetry biases the offset "
            "by half the one-way difference when frequency offsets are zero and "
            "timestamps are noiseless. Synthetic noise, if any, is not a clock measurement."
        ),
    )


def _div_round_nearest(numerator: int, denominator: int) -> int:
    """Round half away from zero. ``denominator`` is positive."""

    if denominator <= 0:
        raise InvalidInput("denominator must be positive")
    sign = 1 if numerator >= 0 else -1
    magnitude = abs(numerator)
    quotient, remainder = divmod(magnitude, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return sign * quotient


def reproducible_noise_samples(sigma_seconds: Decimal, seed: int, count: int) -> tuple[int, ...]:
    """Expose the noise draws so tests can lock the seed without timing physics."""

    if count < 0:
        raise InvalidInput("count must be ≥ 0")
    noise = GaussianTimestampNoise(sigma_seconds, seed)
    rng = noise.generator()
    return tuple(noise.sample_nanoseconds(rng) for _ in range(count))


def gaussian_moments_match_seed(seed: int) -> tuple[float, float]:
    """Mean and variance of 10 000 standard normal draws. Test aid, not a clock."""

    rng = random.Random(seed)
    samples = [rng.gauss(0.0, 1.0) for _ in range(10_000)]
    mean = sum(samples) / len(samples)
    var = sum((x - mean) ** 2 for x in samples) / (len(samples) - 1)
    return mean, var
