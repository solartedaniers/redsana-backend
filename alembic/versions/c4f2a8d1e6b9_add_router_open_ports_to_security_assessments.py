"""add router open ports to security assessments

Revision ID: c4f2a8d1e6b9
Revises: b7c4e1a9d2f3
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f2a8d1e6b9'
down_revision: Union[str, Sequence[str], None] = 'b7c4e1a9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable sin default: las evaluaciones previas nunca escanearon puertos.
    op.add_column('security_assessments', sa.Column('router_open_ports', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('security_assessments', 'router_open_ports')
