"""Create batch imports tables

Revision ID: 007
Revises: 006
Create Date: 2026-06-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_imports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("batch_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "batch_import_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("batch_id", sa.String(64), nullable=False, index=True),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("memory_id", sa.String(128), nullable=True),
        sa.Column("memory", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_batch_import_items_batch_idx", "batch_import_items", ["batch_id", "index"])


def downgrade() -> None:
    op.drop_index("ix_batch_import_items_batch_idx", table_name="batch_import_items")
    op.drop_table("batch_import_items")
    op.drop_table("batch_imports")
