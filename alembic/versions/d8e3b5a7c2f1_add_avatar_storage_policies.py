"""add avatar storage policies

Revision ID: d8e3b5a7c2f1
Revises: c4f2a8d1e6b9
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8e3b5a7c2f1'
down_revision: Union[str, Sequence[str], None] = 'c4f2a8d1e6b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# El bucket "avatars" es público (lectura por URL), pero storage.objects tiene
# RLS activo y no había ninguna política de escritura: Supabase rechazaba toda
# subida con "new row violates row-level security policy". Cada usuario solo
# puede escribir en su propia carpeta ({uid}/avatar.*), que es la ruta que usa
# SupabaseAvatarStorageGateway. SELECT hace falta porque la subida usa upsert.
_OWN_AVATAR_FOLDER = "bucket_id = 'avatars' and (storage.foldername(name))[1] = (select auth.uid())::text"

_POLICIES = {
    'redsana_avatars_insert_own': f"for insert to authenticated with check ({_OWN_AVATAR_FOLDER})",
    'redsana_avatars_update_own': f"for update to authenticated using ({_OWN_AVATAR_FOLDER}) with check ({_OWN_AVATAR_FOLDER})",
    'redsana_avatars_select_own': f"for select to authenticated using ({_OWN_AVATAR_FOLDER})",
}


def upgrade() -> None:
    """Upgrade schema."""
    for name, definition in _POLICIES.items():
        op.execute(f'create policy "{name}" on storage.objects {definition}')


def downgrade() -> None:
    """Downgrade schema."""
    for name in _POLICIES:
        op.execute(f'drop policy if exists "{name}" on storage.objects')
