"""Add M1-B configuration audit and account actor tracking.

Revision ID: 20260806_0002
Revises: 20260806_0001
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0002"
down_revision: str | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)
JSON_OBJECT_DEFAULT = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "platform_accounts",
        sa.Column("updated_by", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "configuration_change_logs",
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "before_data",
            JSONB,
            server_default=JSON_OBJECT_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "after_data",
            JSONB,
            server_default=JSON_OBJECT_DEFAULT,
            nullable=False,
        ),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_configuration_change_logs"),
    )
    op.create_index(
        "ix_configuration_change_logs_entity_created",
        "configuration_change_logs",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_configuration_change_logs_actor_created",
        "configuration_change_logs",
        ["actor", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_configuration_change_logs_actor_created",
        table_name="configuration_change_logs",
    )
    op.drop_index(
        "ix_configuration_change_logs_entity_created",
        table_name="configuration_change_logs",
    )
    op.drop_table("configuration_change_logs")
    op.drop_column("platform_accounts", "updated_by")
