"""Idempotent seed. Safe to run on every deploy."""

from sqlalchemy import select

from app.db import session_scope
from app.models import ProtocolChange, Supplement
from app.seed.supplements import STACK
from app.services.timeutil import utcnow


def main() -> None:
    with session_scope() as session:
        created = 0
        for spec in STACK:
            existing = session.execute(
                select(Supplement).where(Supplement.name == spec["name"])
            ).scalar_one_or_none()
            if existing is not None:
                continue
            supplement = Supplement(**spec)
            session.add(supplement)
            session.flush()
            # Seeding the stack is itself a protocol event: without a dated
            # start there is no "before" for any later before/after analysis.
            session.add(
                ProtocolChange(
                    changed_at=utcnow(),
                    entity_type="supplement",
                    entity_id=supplement.id,
                    change_type="start",
                    new_value=f"{spec.get('dose_amount')} {spec.get('dose_unit')}",
                    rationale="Initial stack seeded at system setup",
                )
            )
            created += 1
        print(f"Seed complete: {created} supplements created, {len(STACK) - created} present.")


if __name__ == "__main__":
    main()
