"""add room_label to hotel_options

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-12 09:20:00.000000

Nullable tag for which room composition produced a hotel result when
search fans out one SerpApi call per distinct occupancy (docs/22).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hotel_options",
        sa.Column("room_label", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hotel_options", "room_label")
