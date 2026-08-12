"""add lock unit price + party size snapshot columns

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-12 09:35:00.000000

Nullable breakdown fields for activity/transport locks so the budget
summary can render unit × party = total (docs/23). Flight/hotel/imported
locks leave both NULL — their locked_price_amount is already a total.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "locks",
        sa.Column("locked_unit_price_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "locks",
        sa.Column("locked_party_size", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("locks", "locked_party_size")
    op.drop_column("locks", "locked_unit_price_amount")
