"""COMPONENT 4.2 -- Fuzzy narration matcher, deterministic core.

Used by engine Stage C's fallback path when a settlement's UTR doesn't turn
up a bank row directly. Deterministic only: normalize case/punctuation, look
for the UTR (or its 8-char prefix) as a substring, else look for a
razorpay-ish token. The optional LLM-assisted 0.5-0.85 ambiguous band
(SS7.2) is a stretch goal and is not implemented -- the deterministic score
is what Stage C's 0.85 accept threshold operates on.
"""
from __future__ import annotations

import re


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def fuzzy_score(narration: str, settlement_utr: str) -> dict:
    """Return {"score": 0..1, "rationale": str} for how well `narration`
    evidences a match to `settlement_utr`."""
    norm = _normalize(narration or "")
    utr = _normalize(settlement_utr or "")

    if utr and utr in norm:
        return {"score": 1.0, "rationale": "full UTR present in narration"}

    prefix = utr[:8]
    if prefix and len(prefix) >= 6 and prefix in norm:
        return {"score": 0.9, "rationale": "UTR prefix present in narration"}

    if any(tok in norm for tok in ("RAZORPAY", "RZPY", "RZP")):
        return {"score": 0.6, "rationale": "razorpay-like token present, UTR not found"}

    return {"score": 0.2, "rationale": "no UTR or razorpay token found in narration"}
