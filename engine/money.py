"""Money utilities. P1: money is integer paise everywhere; floats only at ingest/UI edges.

All monetary values inside the engine are Python ``int`` paise. Conversion from
rupee floats happens once, at ingest. Formatting back to ``₹x.xx`` happens
once, at the UI edge (or in exports).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value: float | int | Decimal) -> int:
    """Round to the nearest integer, ties rounding away from zero (half-up).

    Uses ``Decimal(str(value))`` rather than ``Decimal(value)`` so a float's
    base-10 literal (e.g. ``0.02``) is what gets rounded, not its imprecise
    binary representation.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rupees_to_paise(rupees: float | int | Decimal) -> int:
    """Convert a rupee amount to integer paise. Ingest-edge conversion only."""
    d = rupees if isinstance(rupees, Decimal) else Decimal(str(rupees))
    return round_half_up(d * 100)


def calc_fee_paise(gross_paise: int, fee_rate: float) -> int:
    """fee = round_half_up(gross * fee_rate), in paise."""
    return round_half_up(Decimal(int(gross_paise)) * Decimal(str(fee_rate)))


def calc_gst_paise(fee_paise: int, gst_rate: float = 0.18) -> int:
    """gst = round_half_up(fee * gst_rate), in paise."""
    return round_half_up(Decimal(int(fee_paise)) * Decimal(str(gst_rate)))


def calc_net_paise(gross_paise: int, fee_paise: int, gst_paise: int) -> int:
    """net = gross - fee - gst, per payment."""
    return int(gross_paise) - int(fee_paise) - int(gst_paise)


def effective_fee_rate(base_rate: float, is_instant: bool, instant_premium: float) -> float:
    """Instant-settlement premium is applied additively to the method's base rate."""
    return base_rate + instant_premium if is_instant else base_rate


def within_tolerance(diff_paise: int, expected_paise: int, abs_paise: int, rel: float) -> bool:
    """diff <= min(tolerance.abs_paise, round(tolerance.rel * expected)) -- whichever is smaller."""
    rel_cap = round_half_up(rel * abs(expected_paise))
    return abs(diff_paise) <= min(abs_paise, rel_cap)


def format_inr(paise: int) -> str:
    """Format integer paise as an Indian-grouped rupee string, e.g. 28411000 -> '₹2,84,110.00'."""
    negative = paise < 0
    paise = abs(int(paise))
    rupees, frac = divmod(paise, 100)
    s = str(rupees)
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts: list[str] = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    result = f"₹{grouped}.{frac:02d}"
    return f"-{result}" if negative else result
