"""add booking_sources.booking_post_data

Revision ID: a1c2d3e4f5b6
Revises: 5beabd636c8f
Create Date: 2026-08-08 07:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c2d3e4f5b6"
down_revision: Union[str, Sequence[str], None] = "5beabd636c8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "booking_sources",
        sa.Column("booking_post_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("booking_sources", "booking_post_data")
