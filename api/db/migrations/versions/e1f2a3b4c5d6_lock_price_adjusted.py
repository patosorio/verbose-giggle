"""add lock_event price_adjusted + audit columns

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-12 10:15:00.000000

Post-lock price override audit trail (docs/25). Enum value is widen-only —
Postgres cannot remove enum values on downgrade.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE lock_event_type ADD VALUE IF NOT EXISTS 'price_adjusted'")
    op.add_column(
        "lock_events",
        sa.Column("previous_price_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lock_events",
        sa.Column("new_price_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lock_events",
        sa.Column("previous_currency", sa.String(3), nullable=True),
    )
    op.add_column(
        "lock_events",
        sa.Column("new_currency", sa.String(3), nullable=True),
    )
    op.add_column(
        "lock_events",
        sa.Column("note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lock_events", "note")
    op.drop_column("lock_events", "new_currency")
    op.drop_column("lock_events", "previous_currency")
    op.drop_column("lock_events", "new_price_amount")
    op.drop_column("lock_events", "previous_price_amount")
    # Postgres cannot remove enum values; lock_event_type.price_adjusted remains.
