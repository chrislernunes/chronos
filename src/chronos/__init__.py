"""Chronos: a bounded interplanetary timekeeping library.

Public calculations live in ``earth``, ``mars``, ``relativity``, ``sync``,
and ``reference``. The canonical elapsed time is an integer nanosecond count.
"""

from chronos.core import (
    TT_MINUS_TAI_NANOSECONDS,
    Duration,
    TaiInstant,
    TtInstant,
    tai_to_tt,
    tt_to_tai,
)

__version__ = "0.1.0"

__all__ = [
    "Duration",
    "TT_MINUS_TAI_NANOSECONDS",
    "TaiInstant",
    "TtInstant",
    "__version__",
    "tai_to_tt",
    "tt_to_tai",
]
