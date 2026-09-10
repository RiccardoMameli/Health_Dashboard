"""exercise_templates

Caches Hevy's exercise catalogue locally so a set's exercise_template_id can
be resolved to a muscle group. Hevy serves these one at a time and the
catalogue barely changes, so they are fetched once and kept.

Revision ID: 0003_exercise_templates
Revises: 0002_load_quality
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_exercise_templates"
down_revision = "0002_load_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_templates",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("type", sa.String(32), nullable=True),
        sa.Column("primary_muscle_group", sa.String(32), nullable=True),
        sa.Column("secondary_muscle_groups", sa.JSON(), nullable=True),
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercise_templates")),
    )
    with op.batch_alter_table("exercise_templates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_exercise_templates_primary_muscle_group"),
            ["primary_muscle_group"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("exercise_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_exercise_templates_primary_muscle_group"))
    op.drop_table("exercise_templates")
