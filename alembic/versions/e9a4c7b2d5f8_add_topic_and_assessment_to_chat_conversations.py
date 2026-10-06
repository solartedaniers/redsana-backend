"""add topic and assessment to chat conversations

Revision ID: e9a4c7b2d5f8
Revises: d8e3b5a7c2f1
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a4c7b2d5f8'
down_revision: Union[str, Sequence[str], None] = 'd8e3b5a7c2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TOPIC_ENUM = sa.Enum('assessment_briefing', 'family_mode', name='chat_topic')


def upgrade() -> None:
    """Upgrade schema."""
    _TOPIC_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column('chat_conversations', sa.Column('topic', _TOPIC_ENUM, nullable=True))
    # Único: garantiza un solo mensaje de resumen por evaluación aunque el
    # frontend reintente. SET NULL: borrar la evaluación no borra la conversación.
    op.add_column('chat_conversations', sa.Column('assessment_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_chat_conversations_assessment_id', 'chat_conversations', 'security_assessments',
        ['assessment_id'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_chat_conversations_assessment_id', 'chat_conversations', ['assessment_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_chat_conversations_assessment_id', 'chat_conversations', type_='unique')
    op.drop_constraint('fk_chat_conversations_assessment_id', 'chat_conversations', type_='foreignkey')
    op.drop_column('chat_conversations', 'assessment_id')
    op.drop_column('chat_conversations', 'topic')
    _TOPIC_ENUM.drop(op.get_bind(), checkfirst=True)
