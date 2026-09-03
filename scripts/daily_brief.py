#!/usr/bin/env python3
"""The 06:30 morning job (plan 9.1, 11).

    python scripts/daily_brief.py              # today, generate and send
    python scripts/daily_brief.py --date 2026-09-04 --no-send
    python scripts/daily_brief.py --dry-run    # print the input, spend nothing

Idempotent: the day's brief is upserted, so a retry after a network failure
produces one brief rather than two. Exit codes are meaningful — the cron job
must fail loudly, because a brief that silently stops arriving is the same
failure mode as a sync that silently stops running.
"""

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.ai.client import BriefGenerationError  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services import brief as brief_service  # noqa: E402
from app.services.email import EmailDeliveryError, mark_delivered, send_brief  # noqa: E402
from app.services.timeutil import local_date, utcnow  # noqa: E402

EXIT_OK = 0
EXIT_GENERATION_FAILED = 1
EXIT_DELIVERY_FAILED = 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--no-send", action="store_true", help="generate only")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the computed input contract and exit without calling the model",
    )
    args = parser.parse_args()

    settings = get_settings()
    day = args.date or local_date(utcnow())

    with session_scope() as session:
        if args.dry_run:
            print(json.dumps(brief_service.prepare_input(session, day, settings), indent=2))
            return EXIT_OK

        try:
            brief = brief_service.generate_and_store(session, day, settings=settings)
        except BriefGenerationError as exc:
            print(f"brief generation failed for {day}: {exc}", file=sys.stderr)
            return EXIT_GENERATION_FAILED

        verification = (brief.output or {}).get("verification", {})
        if not verification.get("numbers_traceable", True):
            # Loud, but not fatal: the brief exists and is flagged. A silent
            # pass here would defeat the point of checking at all.
            print(
                f"warning: brief for {day} quoted numbers absent from its input: "
                f"{verification.get('untraceable_numbers')}",
                file=sys.stderr,
            )

        print(f"brief generated for {day}: {(brief.output or {}).get('status')}")

        if args.no_send:
            return EXIT_OK

        try:
            message_id = send_brief(brief, settings)
        except EmailDeliveryError as exc:
            print(f"delivery failed for {day}: {exc}", file=sys.stderr)
            return EXIT_DELIVERY_FAILED

        mark_delivered(session, brief, "email")
        print(f"delivered: {message_id}")
        return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
