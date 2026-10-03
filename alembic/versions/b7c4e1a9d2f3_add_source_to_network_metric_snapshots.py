"""add source to network metric snapshots

Revision ID: b7c4e1a9d2f3
Revises: 9ddcdf577baf
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e1a9d2f3'
down_revision: Union[str, Sequence[str], None] = '9ddcdf577baf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_ENUM = sa.Enum('native', 'web', name='measurement_source')


def upgrade() -> None:
    """Upgrade schema."""
    _SOURCE_ENUM.create(op.get_bind(), checkfirst=True)
    # Todo el historial existente viene de ping.rs (la medicion web no existia).
    op.add_column(
        'network_metric_snapshots',
        sa.Column('source', _SOURCE_ENUM, nullable=False, server_default='native'),
    )
    op.create_index(
        'ix_network_metric_snapshots_owner_source_recorded',
        'network_metric_snapshots',
        ['owner_id', 'source', 'recorded_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_network_metric_snapshots_owner_source_recorded', table_name='network_metric_snapshots')
    op.drop_column('network_metric_snapshots', 'source')
    _SOURCE_ENUM.drop(op.get_bind(), checkfirst=True)
