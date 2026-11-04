import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.authorization import ADMIN_ROLE_NAME
from app.core.security import decode_supabase_token
from app.realtime.connections import CloseCode
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.services.user_service import UserService


@dataclass(frozen=True)
class RealtimeIdentity:
    user_id: uuid.UUID
    is_admin: bool
    expires_at: float


class RealtimeAuthError(Exception):
    def __init__(self, close_code: CloseCode) -> None:
        super().__init__(close_code.name)
        self.close_code = close_code


class RealtimeAuthenticator(ABC):
    """Síncrono a propósito: valida el JWT (puede pedir el JWKS) y lee la base, así que corre en un hilo."""

    @abstractmethod
    def authenticate(self, token: str) -> RealtimeIdentity: ...


class SupabaseRealtimeAuthenticator(RealtimeAuthenticator):
    """Las mismas reglas que la API REST: JWT de Supabase, cuenta suspendida fuera y rol leído de la base."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def authenticate(self, token: str) -> RealtimeIdentity:
        try:
            claims = decode_supabase_token(token)
        except HTTPException as error:
            raise RealtimeAuthError(CloseCode.UNAUTHORIZED) from error
        with self._session_factory() as db:
            try:
                user = UserService(SqlAlchemyUserRepository(db)).get_or_create_current_user(claims)
            except (KeyError, ValueError) as error:
                raise RealtimeAuthError(CloseCode.UNAUTHORIZED) from error
            if user.is_active is False:
                raise RealtimeAuthError(CloseCode.FORBIDDEN)
            return RealtimeIdentity(
                user_id=user.id, is_admin=user.role.name == ADMIN_ROLE_NAME, expires_at=float(claims["exp"])
            )
