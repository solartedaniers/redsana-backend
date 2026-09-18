import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.authorization import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.supabase_admin_client import SupabaseAdminClient
from app.models.user import User
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.admin import AdminUserCreate, AdminUserRead, AdminUserUpdate
from app.services.admin_user_service import AdminUserService, UserNotFoundError

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


def _to_user_read(user: User) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role.name,
        status="active" if user.is_active else "suspended",
        created_at=user.created_at,
    )


def _build_service(db: Session) -> AdminUserService:
    return AdminUserService(SqlAlchemyUserRepository(db), SupabaseAdminClient(get_settings()))


@router.get("", response_model=list[AdminUserRead])
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserRead]:
    return [_to_user_read(user) for user in _build_service(db).list_users()]


@router.post("", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserRead:
    return _to_user_read(_build_service(db).create_user(payload))


@router.patch("/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserRead:
    try:
        user = _build_service(db).update_user(user_id, payload)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from error
    return _to_user_read(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        _build_service(db).delete_user(user_id)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from error
