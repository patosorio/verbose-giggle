"""phase 4.5 transport option, nullable tier, citation option_card_id

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-08 11:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE option_type ADD VALUE IF NOT EXISTS 'transport' BEFORE 'imported'")
    op.execute(
        "ALTER TYPE research_run_type ADD VALUE IF NOT EXISTS 'transport' BEFORE 'full'"
    )

    op.alter_column(
        "option_cards",
        "tier",
        existing_type=postgresql.ENUM(
            "budget", "comfort", "premium", name="budget_band", create_type=False
        ),
        nullable=True,
    )

    transport_mode = postgresql.ENUM(
        "ferry",
        "train",
        "bus",
        "private_van",
        "other",
        name="transport_mode",
        create_type=True,
    )
    transport_mode.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "transport_options",
        sa.Column("option_card_id", sa.UUID(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "ferry",
                "train",
                "bus",
                "private_van",
                "other",
                name="transport_mode",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("operator_name", sa.String(), nullable=True),
        sa.Column("departure_point", sa.Text(), nullable=False),
        sa.Column("arrival_point", sa.Text(), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("estimated_price_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("estimated_price_currency", sa.String(length=3), nullable=True),
        sa.Column("booking_url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["option_card_id"], ["option_cards.id"]),
        sa.PrimaryKeyConstraint("option_card_id"),
    )

    op.drop_constraint(
        "citations_activity_option_id_fkey",
        "citations",
        type_="foreignkey",
    )
    op.alter_column(
        "citations",
        "activity_option_id",
        new_column_name="option_card_id",
        existing_type=sa.UUID(),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "citations_option_card_id_fkey",
        "citations",
        "option_cards",
        ["option_card_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("citations_option_card_id_fkey", "citations", type_="foreignkey")
    op.alter_column(
        "citations",
        "option_card_id",
        new_column_name="activity_option_id",
        existing_type=sa.UUID(),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "citations_activity_option_id_fkey",
        "citations",
        "activity_options",
        ["activity_option_id"],
        ["option_card_id"],
    )

    op.drop_table("transport_options")
    op.execute("DROP TYPE IF EXISTS transport_mode")

    # Widen-only change — refuse to re-narrow if any null tiers exist.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM option_cards WHERE tier IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade option_cards.tier to NOT NULL while null tiers exist';
            END IF;
        END $$;
        """
    )
    op.alter_column(
        "option_cards",
        "tier",
        existing_type=postgresql.ENUM(
            "budget", "comfort", "premium", name="budget_band", create_type=False
        ),
        nullable=False,
    )
    # Postgres cannot remove enum values; option_type.transport and
    # research_run_type.transport remain after downgrade.
