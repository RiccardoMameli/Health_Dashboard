"""The AI layer (plan 9).

The model prioritises, explains and writes. It never calculates: everything
it receives has already been computed by `app.metrics`, and everything it
writes back is checked against that input by `app.ai.verify`.
"""

from app.ai.client import BriefGenerationError, GeneratedBrief, generate_brief
from app.ai.prompts import PROMPT_VERSION, system_prompt
from app.ai.schemas import BriefOutput
from app.ai.verify import untraceable_numbers

__all__ = [
    "PROMPT_VERSION",
    "BriefGenerationError",
    "BriefOutput",
    "GeneratedBrief",
    "generate_brief",
    "system_prompt",
    "untraceable_numbers",
]
