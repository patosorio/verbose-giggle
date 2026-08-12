"""add option_cards FX snapshot columns for convert-at-persist

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-12 09:55:00.000000

When agent-researched activity/transport prices arrive in a non-home currency,
persist converts to Trip.home_currency on OptionCard and snapshots the original
amount/rate (architecture §9.1 exception — convert at research persist).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "option_cards",
        sa.Column("original_price_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "option_cards",
        sa.Column("original_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "option_cards",
        sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True),
    )
    op.add_column(
        "option_cards",
        sa.Column("fx_rate_as_of", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("option_cards", "fx_rate_as_of")
    op.drop_column("option_cards", "fx_rate")
    op.drop_column("option_cards", "original_currency")
    op.drop_column("option_cards", "original_price_amount")
