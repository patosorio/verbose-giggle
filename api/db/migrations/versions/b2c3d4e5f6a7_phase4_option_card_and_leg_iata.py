"""phase4 option_card research_run/superseded + leg iata

Revision ID: b2c3d4e5f6a7
Revises: a1c2d3e4f5b6
Create Date: 2026-08-08 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1c2d3e4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("legs", sa.Column("origin_iata", sa.String(length=3), nullable=True))
    op.add_column("legs", sa.Column("destination_iata", sa.String(length=3), nullable=True))
    op.add_column(
        "option_cards",
        sa.Column("research_run_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "option_cards",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_option_cards_research_run_id_research_runs",
        "option_cards",
        "research_runs",
        ["research_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_option_cards_research_run_id_research_runs",
        "option_cards",
        type_="foreignkey",
    )
    op.drop_column("option_cards", "superseded_at")
    op.drop_column("option_cards", "research_run_id")
    op.drop_column("legs", "destination_iata")
    op.drop_column("legs", "origin_iata")
