"""daily_metrics.load_quality

Records which definition produced a day's training load — duration x RPE or
volume — so a stored acute:chronic ratio can be read later with the right
amount of confidence. Without it, a ratio computed from three years of
volume-only history is indistinguishable from one computed from RPE, and the
brief has no honest way to qualify what it is reporting.

Revision ID: 0002_load_quality
Revises: 0001_initial_schema
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_load_quality"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no backfill on purpose: rows computed before this column
    # existed genuinely do not know their basis, and a null says that. Guessing
    # "volume_based" for them would be an assumption dressed as a record.
    op.add_column("daily_metrics", sa.Column("load_quality", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_metrics", "load_quality")
