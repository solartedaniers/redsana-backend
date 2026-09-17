"""create roles and users tables

Revision ID: 2912dcec10e7
Revises: 
Create Date: 2026-09-17 12:27:28.306873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2912dcec10e7'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role_id", sa.SmallInteger(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email"),
    )

    # roles base de la plataforma, usados para el auto-provisioning en el primer login
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", sa.SmallInteger()),
            sa.column("name", sa.String()),
            sa.column("description", sa.String()),
        ),
        [
            {"id": 1, "name": "standard", "description": "Usuario estandar"},
            {"id": 2, "name": "admin", "description": "Administrador de la plataforma"},
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("users")
    op.drop_table("roles")
