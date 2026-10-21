"""High-precision helpers used only where the rounding must be explicit."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from chronos.core import InvalidInput, NANOSECONDS_PER_SECOND

# 80 decimal digits is far past a nanosecond on solar-system intervals
# (10^9 s × 10^9 ns ≈ 10^18, and 80 digits leaves margin for irrational roots).
DECIMAL_PRECISION = 80


def nanoseconds_from_seconds(seconds: Decimal) -> int:
    """Round an exact decimal second-count to the nearest SI nanosecond."""

    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        scaled = (seconds * Decimal(NANOSECONDS_PER_SECOND)).to_integral_value(
            rounding=ROUND_HALF_EVEN
        )
    return int(scaled)


def scale_nanoseconds(nanoseconds: int, factor: Decimal) -> int:
    """Return ``round(nanoseconds × factor)`` to the nearest nanosecond."""

    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        scaled = (Decimal(nanoseconds) * factor).to_integral_value(rounding=ROUND_HALF_EVEN)
    return int(scaled)


def decimal_sqrt(value: Decimal) -> Decimal:
    if value < 0:
        raise InvalidInput("square root of a negative quantity")
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return value.sqrt()
