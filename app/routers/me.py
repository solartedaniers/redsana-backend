from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims
from app.models.user import User
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.user import UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/api", tags=["users"])

CURRENT_USER_PATH = "/users/me"
# Ruta anterior: la siguen usando el instalador 0.1.5 y la web ya desplegada; queda fuera de la documentación.
LEGACY_CURRENT_USER_PATH = "/me"


def _to_user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        role=user.role.name,
        is_active=user.is_active,
    )


def _get_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(SqlAlchemyUserRepository(db))


@router.get(CURRENT_USER_PATH, response_model=UserRead)
@router.get(LEGACY_CURRENT_USER_PATH, response_model=UserRead, include_in_schema=False)
def read_current_user(
    claims: dict[str, Any] = Depends(get_current_claims),
    service: UserService = Depends(_get_service),
) -> UserRead:
    user = service.get_or_create_current_user(claims)
    return _to_user_read(user)


@router.patch(CURRENT_USER_PATH, response_model=UserRead)
@router.patch(LEGACY_CURRENT_USER_PATH, response_model=UserRead, include_in_schema=False)
def update_current_user(
    payload: UserUpdate,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: UserService = Depends(_get_service),
) -> UserRead:
    user = service.update_current_user(claims, payload)
    return _to_user_read(user)
