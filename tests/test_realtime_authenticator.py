"""El autenticador del socket aplica las reglas de la API REST: token válido, cuenta activa y rol leído de la base."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.role import Role
from app.models.user import User
from app.realtime.authenticator import RealtimeAuthError, SupabaseRealtimeAuthenticator
from app.realtime.connections import CloseCode

USER_ID = uuid.uuid4()
EXPIRES_AT = 2_000_000_000
STANDARD_ROLE_ID = 1
ADMIN_ROLE_ID = 2


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([Role(id=STANDARD_ROLE_ID, name="standard"), Role(id=ADMIN_ROLE_ID, name="admin")])
        db.commit()
    yield factory
    Base.metadata.drop_all(engine)


def _accept_token(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = {"sub": str(USER_ID), "email": "user@example.com", "exp": EXPIRES_AT}
    monkeypatch.setattr("app.realtime.authenticator.decode_supabase_token", lambda _token: claims)


def _add_user(session_factory, role_id: int, is_active: bool = True) -> None:
    with session_factory() as db:
        db.add(User(id=USER_ID, email="user@example.com", role_id=role_id, is_active=is_active))
        db.commit()


def test_a_valid_token_gives_the_user_and_when_it_expires(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    _accept_token(monkeypatch)

    identity = SupabaseRealtimeAuthenticator(session_factory).authenticate("token")

    assert (identity.user_id, identity.is_admin, identity.expires_at) == (USER_ID, False, EXPIRES_AT)


def test_the_admin_role_comes_from_the_database(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    _accept_token(monkeypatch)
    _add_user(session_factory, ADMIN_ROLE_ID)

    assert SupabaseRealtimeAuthenticator(session_factory).authenticate("token").is_admin


def test_a_suspended_account_is_forbidden(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    _accept_token(monkeypatch)
    _add_user(session_factory, STANDARD_ROLE_ID, is_active=False)

    with pytest.raises(RealtimeAuthError) as error:
        SupabaseRealtimeAuthenticator(session_factory).authenticate("token")

    assert error.value.close_code == CloseCode.FORBIDDEN


def test_an_invalid_token_is_unauthorized(session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_token: str) -> dict:
        raise HTTPException(status_code=401, detail="Invalid token")

    monkeypatch.setattr("app.realtime.authenticator.decode_supabase_token", reject)

    with pytest.raises(RealtimeAuthError) as error:
        SupabaseRealtimeAuthenticator(session_factory).authenticate("token")

    assert error.value.close_code == CloseCode.UNAUTHORIZED
