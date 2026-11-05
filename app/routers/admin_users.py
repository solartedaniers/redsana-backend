import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.cache.owner_cache import OwnerCache
from app.core.authorization import require_admin
from app.core.cache_composition import get_owner_cache
from app.core.config import get_settings
from app.core.database import get_db
from app.core.realtime_composition import get_event_publisher
from app.core.supabase_admin_client import SupabaseAdminClient
from app.models.user import User
from app.realtime.events import ACCESS_CHANGED, RealtimeEvent
from app.realtime.publisher import EventPublisher
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.admin import AdminUserCreate, AdminUserRead, AdminUserUpdate
from app.services.admin_user_service import AdminLockoutError, AdminUserService, EmailTakenError, UserNotFoundError

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

# 422 y no 409: el frontend 0.2.1 ya trata cualquier 409 como el bloqueo del admin.
EMAIL_TAKEN_DETAIL = "email_taken"


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
    try:
        return _to_user_read(_build_service(db).create_user(payload))
    except EmailTakenError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=EMAIL_TAKEN_DETAIL) from error


@router.patch("/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_event_publisher),
) -> AdminUserRead:
    try:
        user = _build_service(db).update_user(user_id, payload, acting_admin_id=admin.id)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from error
    except AdminLockoutError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if payload.role is not None or payload.status is not None:
        publisher.publish(RealtimeEvent.now(ACCESS_CHANGED, user_id))
    return _to_user_read(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    cache: OwnerCache = Depends(get_owner_cache),
    publisher: EventPublisher = Depends(get_event_publisher),
) -> None:
    try:
        _build_service(db).delete_user(user_id, acting_admin_id=admin.id)
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from error
    except AdminLockoutError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    # El borrado arrastra sus mediciones y dispositivos: un admin no debe ver los suyos en caché.
    cache.invalidate(user_id)
    publisher.publish(RealtimeEvent.now(ACCESS_CHANGED, user_id))
