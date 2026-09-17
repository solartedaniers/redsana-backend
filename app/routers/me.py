from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.user import UserRead
from app.services.user_service import UserService

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=UserRead)
def read_current_user(
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> UserRead:
    service = UserService(SqlAlchemyUserRepository(db))
    user = service.get_or_create_current_user(claims)
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.name,
        is_active=user.is_active,
    )
