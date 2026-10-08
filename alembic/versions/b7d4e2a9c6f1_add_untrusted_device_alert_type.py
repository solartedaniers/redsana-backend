"""add untrusted_device alert type

Revision ID: b7d4e2a9c6f1
Revises: a3c8e5f1b7d2
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7d4e2a9c6f1'
down_revision: Union[str, Sequence[str], None] = 'a3c8e5f1b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREVIOUS_ALERT_TYPES = ("outage", "prediction")
NEW_ALERT_TYPE = "untrusted_device"


def upgrade() -> None:
    """Upgrade schema."""
    # Aditiva: solo agrega un valor al ENUM, las filas existentes no cambian.
    op.execute(f"ALTER TYPE alert_type ADD VALUE IF NOT EXISTS '{NEW_ALERT_TYPE}'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres no permite quitar un valor de un ENUM: se recrea sin él. Las
    # alertas de ese tipo no pueden existir con el ENUM viejo y se borran.
    op.execute(f"DELETE FROM alerts WHERE type = '{NEW_ALERT_TYPE}'")
    op.execute("ALTER TYPE alert_type RENAME TO alert_type_old")
    values = ", ".join(f"'{value}'" for value in PREVIOUS_ALERT_TYPES)
    op.execute(f"CREATE TYPE alert_type AS ENUM ({values})")
    op.execute("ALTER TABLE alerts ALTER COLUMN type TYPE alert_type USING type::text::alert_type")
    op.execute("DROP TYPE alert_type_old")
