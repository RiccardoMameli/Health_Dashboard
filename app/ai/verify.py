"""Traceability check: every number in a brief must come from the input.

This is the Phase 2 acceptance gate in code (plan §14): "every number in it
traces back to the input JSON". Rule 1 of §9.2 is the one rule a language
model is most likely to break convincingly — a converted unit or a tidied
average reads exactly like a real measurement — so it is checked rather than
trusted.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.schemas import BriefOutput

#: A number, with optional sign, thousands separators and decimal part.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: Stripped before scanning: an ISO date is a label, not a measurement.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _collect(node: Any, numbers: set[float], strings: list[str]) -> None:
    if isinstance(node, bool):  # bool is an int subclass; not a measurement
        return
    if isinstance(node, (int, float)):
        numbers.add(float(node))
    elif isinstance(node, str):
        strings.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            strings.append(str(key))
            _collect(value, numbers, strings)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect(value, numbers, strings)


def _brief_text(output: BriefOutput) -> str:
    """Every field a reader actually reads."""
    parts: list[str] = [output.headline]
    parts += [w.observation for w in output.why]
    parts += [w.evidence for w in output.why]
    parts += [a.action for a in output.do_today]
    parts += [a.rationale for a in output.do_today]
    parts += output.avoid_today
    parts += output.watch_items
    parts += output.data_caveats
    if output.training_recommendation:
        parts.append(output.training_recommendation.rationale)
    if output.supplement_note:
        parts.append(output.supplement_note)
    if output.proposed_experiment:
        parts.append(output.proposed_experiment)
    return "\n".join(parts)


def untraceable_numbers(output: BriefOutput, payload: dict) -> list[str]:
    """Numbers the brief states that the input does not contain.

    A value counts as traceable when an input number rounds to it at the
    precision it was written to — quoting 84.2 for a stored 84.23 is
    reporting, not invention. A unit conversion is not traceable, and that is
    deliberate: "5h42m" from a stored 342 minutes is arithmetic the model was
    told not to do.
    """
    numbers: set[float] = set()
    strings: list[str] = []
    _collect(payload, numbers, strings)
    haystack = " ".join(strings)

    violations: list[str] = []
    for token in _NUMBER.findall(_ISO_DATE.sub(" ", _brief_text(output))):
        cleaned = token.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:  # pragma: no cover - the regex cannot produce this
            continue

        decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
        tolerance = 0.5 * (10**-decimals)
        if any(abs(candidate - value) <= tolerance for candidate in numbers):
            continue
        # A figure quoted from a string field (a workout title, a tag) is fine.
        if cleaned in haystack or token in haystack:
            continue
        violations.append(token)

    return sorted(set(violations), key=violations.index)
