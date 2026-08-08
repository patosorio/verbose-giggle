"""unique legs (trip_id, sequence_index)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-08 10:05:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Requires existing duplicate (trip_id, sequence_index) rows to be cleaned first —
    # this migration does not delete or rewrite leg data.
    op.create_unique_constraint(
        "uq_legs_trip_id_sequence_index",
        "legs",
        ["trip_id", "sequence_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_legs_trip_id_sequence_index", "legs", type_="unique")
