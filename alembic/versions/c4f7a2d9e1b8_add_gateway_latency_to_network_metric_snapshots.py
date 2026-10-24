"""add gateway latency to network metric snapshots

Revision ID: c4f7a2d9e1b8
Revises: b7d4e2a9c6f1
Create Date: 2026-10-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f7a2d9e1b8"
down_revision: str | Sequence[str] | None = "b7d4e2a9c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable y sin default: las filas existentes no se reescriben y quedan sin dato del router (no se diagnostican).
    op.add_column("network_metric_snapshots", sa.Column("gateway_latency_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("network_metric_snapshots", "gateway_latency_ms")
