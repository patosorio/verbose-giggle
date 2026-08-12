"""phase 5.5 manual option — nullable source_url + raw_response_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08 14:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "imported_options",
        "source_url",
        existing_type=sa.String(),
        nullable=True,
    )
    op.alter_column(
        "option_cards",
        "raw_response_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "option_cards",
        "raw_response_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.alter_column(
        "imported_options",
        "source_url",
        existing_type=sa.String(),
        nullable=False,
    )
