"""add explicit timezone to datetime columns

Revision ID: 8a25c8b4fe89
Revises: 49ff334b38a0
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a25c8b4fe89'
down_revision: Union[str, Sequence[str], None] = '49ff334b38a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Estas columnas se guardaban como timestamp sin zona horaria, pero el valor ya
# estaba en UTC (server_default=now() con el servidor en UTC). Por eso la
# conversión solo etiqueta el offset con AT TIME ZONE, no desplaza el dato.
_DATETIME_COLUMNS = [
    ("network_metric_snapshots", "recorded_at"),
    ("alerts", "created_at"),
    ("devices", "first_seen"),
    ("devices", "last_seen"),
    ("users", "created_at"),
    ("users", "updated_at"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in _DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
