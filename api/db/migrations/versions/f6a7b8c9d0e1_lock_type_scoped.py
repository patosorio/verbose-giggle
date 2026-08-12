"""lock uniqueness scoped by (leg_id, option_type) for single-lock types

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-09 18:45:00.000000

The single-lock option_type list in the partial unique index predicate
(flight/hotel/imported) is duplicated in services/lock.py's
SINGLE_LOCK_OPTION_TYPES and in db/models.py Lock.__table_args__. There is
no single source of truth — keep all three in sync when changing the set.
See also db/models.py Lock.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reuse option_cards' enum — create_type=False so we don't redefine it.
_option_type = postgresql.ENUM(
    "flight",
    "hotel",
    "activity",
    "transport",
    "imported",
    name="option_type",
    create_type=False,
)


def upgrade() -> None:
    op.add_column("locks", sa.Column("option_type", _option_type, nullable=True))
    op.execute(
        """
        UPDATE locks
        SET option_type = option_cards.option_type
        FROM option_cards
        WHERE option_cards.id = locks.option_card_id
        """
    )
    op.alter_column("locks", "option_type", existing_type=_option_type, nullable=False)
    op.drop_index(
        "uq_locks_leg_id_active",
        table_name="locks",
        postgresql_where=sa.text("unlocked_at IS NULL"),
    )
    # Predicate must stay aligned with SINGLE_LOCK_OPTION_TYPES in services/lock.py
    # and Lock.__table_args__ in db/models.py.
    op.create_index(
        "uq_locks_leg_id_option_type_active",
        "locks",
        ["leg_id", "option_type"],
        unique=True,
        postgresql_where=sa.text(
            "unlocked_at IS NULL AND option_type IN ('flight', 'hotel', 'imported')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_locks_leg_id_option_type_active",
        table_name="locks",
        postgresql_where=sa.text(
            "unlocked_at IS NULL AND option_type IN ('flight', 'hotel', 'imported')"
        ),
    )
    op.create_index(
        "uq_locks_leg_id_active",
        "locks",
        ["leg_id"],
        unique=True,
        postgresql_where=sa.text("unlocked_at IS NULL"),
    )
    op.drop_column("locks", "option_type")
