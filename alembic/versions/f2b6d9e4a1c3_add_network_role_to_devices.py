"""add network role to devices

Revision ID: f2b6d9e4a1c3
Revises: e9a4c7b2d5f8
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b6d9e4a1c3'
down_revision: Union[str, Sequence[str], None] = 'e9a4c7b2d5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_ENUM = sa.Enum('this_device', 'gateway', 'other', name='device_network_role')


def upgrade() -> None:
    """Upgrade schema."""
    _ROLE_ENUM.create(op.get_bind(), checkfirst=True)
    # Nullable: los dispositivos ya guardados no tienen papel conocido hasta
    # que un escaneo nuevo los vuelva a ver.
    op.add_column('devices', sa.Column('network_role', _ROLE_ENUM, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('devices', 'network_role')
    _ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
