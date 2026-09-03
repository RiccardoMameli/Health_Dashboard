"""The Anthropic call behind the daily brief (plan 9).

One request, structured output, validated on arrival. The model receives the
pre-computed §9.1 summary and nothing else — never a raw time-series.

Failures are raised, not swallowed: a brief that could not be generated must
show up as a failure, in the same spirit as the sync-run bookkeeping. A
morning with no brief is recoverable; a morning with a quietly invented one
is not.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic

from app.ai.prompts import PROMPT_VERSION, correction_prompt, system_prompt, user_prompt
from app.ai.schemas import BriefOutput
from app.ai.verify import untraceable_numbers
from app.config import Settings, get_settings

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

#: One retry when the traceability check fails, naming the offending numbers.
MAX_TRACEABILITY_ATTEMPTS = 2


class BriefGenerationError(RuntimeError):
    """The brief could not be generated. Never returns a partial brief."""


@dataclass
class GeneratedBrief:
    output: BriefOutput
    model: str
    prompt_version: str
    attempts: int
    untraceable_numbers: list[str]

    @property
    def verified(self) -> bool:
        return not self.untraceable_numbers


def _client(settings: Settings) -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise BriefGenerationError(
            "ANTHROPIC_API_KEY is not set. The brief needs a key; it will not "
            "fall back to a template, because a templated brief that looks "
            "generated is worse than no brief."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def generate_brief(
    payload: dict,
    *,
    phase: str,
    settings: Settings | None = None,
    client: anthropic.Anthropic | None = None,
) -> GeneratedBrief:
    """Write one daily brief from the computed summary.

    Raises `BriefGenerationError` on anything that would otherwise produce a
    brief the system cannot stand behind.
    """
    settings = settings or get_settings()
    client = client or _client(settings)

    payload_json = json.dumps(payload, indent=2, sort_keys=True)
    messages: list[dict] = [{"role": "user", "content": user_prompt(payload_json)}]

    last: BriefOutput | None = None
    violations: list[str] = []

    for attempt in range(1, MAX_TRACEABILITY_ATTEMPTS + 1):
        try:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt(phase),
                        # The prompt is identical every morning; the payload
                        # never is. Caching the stable half is free.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                thinking={"type": "adaptive"},
                messages=messages,
                output_format=BriefOutput,
            )
        except anthropic.APIStatusError as exc:
            raise BriefGenerationError(f"Anthropic API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise BriefGenerationError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise BriefGenerationError(f"Model declined to answer: {response.stop_details}")

        last = response.parsed_output
        if last is None:
            raise BriefGenerationError("Model returned no parseable brief.")

        violations = untraceable_numbers(last, payload)
        if not violations:
            return GeneratedBrief(
                output=last,
                model=response.model,
                prompt_version=PROMPT_VERSION,
                attempts=attempt,
                untraceable_numbers=[],
            )

        log.warning(
            "Brief attempt %s stated numbers absent from the input: %s",
            attempt,
            violations,
        )
        if attempt < MAX_TRACEABILITY_ATTEMPTS:
            messages += [
                {"role": "assistant", "content": last.model_dump_json()},
                {"role": "user", "content": correction_prompt(violations)},
            ]

    # Kept, flagged, and surfaced — the operator needs to see this happening.
    return GeneratedBrief(
        output=last,
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        attempts=MAX_TRACEABILITY_ATTEMPTS,
        untraceable_numbers=violations,
    )
