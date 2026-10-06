"""add network id to network metric snapshots

Revision ID: a3c8e5f1b7d2
Revises: f2b6d9e4a1c3
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c8e5f1b7d2'
down_revision: Union[str, Sequence[str], None] = 'f2b6d9e4a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable y sin default: el historial existente no tiene red conocida y no
    # se asigna a ninguna adivinando (ver app.domain.network_baseline).
    op.add_column('network_metric_snapshots', sa.Column('network_id', sa.String(length=64), nullable=True))
    op.create_index(
        'ix_network_metric_snapshots_owner_source_network_recorded',
        'network_metric_snapshots',
        ['owner_id', 'source', 'network_id', 'recorded_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_network_metric_snapshots_owner_source_network_recorded', table_name='network_metric_snapshots')
    op.drop_column('network_metric_snapshots', 'network_id')
