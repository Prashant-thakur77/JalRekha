"""Text guardrails for anything a language model writes for officials.

``numbers_from_tools``: every number in model text must equal (within
rounding) a number that appeared in the cycle's tool outputs. If not, the
text is rejected and the deterministic template is used instead.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> list[float]:
    out = []
    for tok in NUM.findall((text or "").translate(DEVA_DIGITS)):
        try:
            out.append(float(tok.replace(",", ".")))
        except ValueError:
            continue
    return out


def _collect(obj: Any, acc: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, str):
        acc.extend(numbers_in(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, acc)


def numbers_from_tools(text: str, tool_outputs: Iterable[Any], *, rel_tol: float = 0.051, abs_tol: float = 0.051) -> dict[str, Any]:
    allowed: list[float] = []
    for o in tool_outputs:
        _collect(o, allowed)
    bad = []
    for n in numbers_in(text):
        if not any(abs(n - a) <= max(abs_tol, rel_tol * abs(a)) for a in allowed):
            bad.append(n)
    return {"ok": not bad, "unsupported_numbers": bad, "checked": len(numbers_in(text))}


INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior) (instructions|rules)|system (note|prompt)|you are now|cancel all alerts|"
    r"switch the siren off|disregard (the )?(rules|instructions)|"
    # Hindi / Nepali: "cancel (all) alerts", "turn off the siren", "ignore the rules"
    r"अलर्ट रद्द|चेतावनी रद्द|सूचना रद्द|सायरन बंद|साइरन बन्द|नियम(ों)? (को )?(अनदेखा|नज़रअंदाज़|नजरअंदाज)|निर्देश(ों)? (को )?अनदेखा)",
    re.I,
)


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text or ""))
