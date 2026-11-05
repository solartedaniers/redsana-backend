"""Crear un usuario con un correo ya registrado responde 422 "email_taken"; los demás fallos siguen como antes."""

import io
import json
import urllib.error
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import supabase_admin_client
from app.core.authorization import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.supabase_admin_client import SupabaseAdminClient, SupabaseAdminError, SupabaseEmailTakenError
from app.models.base import Base
from app.models.role import Role
from app.models.user import User
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.routers import admin_users
from app.schemas.admin import AdminUserCreate
from app.services.admin_user_service import AdminUserService, EmailTakenError
from tests.test_admin_user_service import FakeSupabaseAdminClient
from tests.test_user_service import FakeUserRepository

NEW_USER = {"full_name": "Ana", "email": "ana@redsana.dev", "role": "standard"}


class _RejectingSupabaseAdminClient(FakeSupabaseAdminClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def invite_user(self, email: str, full_name: str | None) -> uuid.UUID:
        self.invited.append((email, full_name))
        raise self._error


def _client_with(service: AdminUserService, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(admin_users, "_build_service", lambda _db: service)
    api = FastAPI()
    api.include_router(admin_users.router)
    api.dependency_overrides[require_admin] = lambda: object()
    api.dependency_overrides[get_db] = lambda: None
    return TestClient(api, raise_server_exceptions=False)


def _supabase_http_error(status: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.invalid", status, "x", {}, io.BytesIO(json.dumps(body).encode()))


def test_an_email_already_in_the_database_is_refused_without_inviting() -> None:
    repository = FakeUserRepository()
    repository.create(uuid.uuid4(), "Ana@RedSana.dev", "Ana", "standard")
    supabase = FakeSupabaseAdminClient()

    with pytest.raises(EmailTakenError):
        AdminUserService(repository, supabase).create_user(AdminUserCreate(**NEW_USER))
    assert supabase.invited == []


def test_supabase_rejecting_the_email_becomes_email_taken() -> None:
    service = AdminUserService(FakeUserRepository(), _RejectingSupabaseAdminClient(SupabaseEmailTakenError("x")))

    with pytest.raises(EmailTakenError):
        service.create_user(AdminUserCreate(**NEW_USER))


@pytest.mark.parametrize("error_code", ["email_exists", "user_already_exists"])
def test_the_supabase_client_recognizes_the_email_taken_codes(monkeypatch: pytest.MonkeyPatch, error_code: str) -> None:
    def rejecting_urlopen(request, timeout=None):
        raise _supabase_http_error(422, {"code": 422, "error_code": error_code, "msg": "already registered"})

    monkeypatch.setattr(supabase_admin_client.urllib.request, "urlopen", rejecting_urlopen)

    with pytest.raises(SupabaseEmailTakenError):
        SupabaseAdminClient(get_settings()).invite_user("ana@redsana.dev", "Ana")


def test_other_supabase_errors_stay_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    def rejecting_urlopen(request, timeout=None):
        raise _supabase_http_error(422, {"code": 422, "error_code": "validation_failed", "msg": "bad email"})

    monkeypatch.setattr(supabase_admin_client.urllib.request, "urlopen", rejecting_urlopen)

    with pytest.raises(SupabaseAdminError) as raised:
        SupabaseAdminClient(get_settings()).invite_user("ana@redsana.dev", "Ana")
    assert not isinstance(raised.value, SupabaseEmailTakenError)


def test_the_endpoint_answers_422_email_taken_without_supabase_details(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = SupabaseEmailTakenError("Supabase secret detail")
    client = _client_with(AdminUserService(FakeUserRepository(), _RejectingSupabaseAdminClient(rejection)), monkeypatch)

    response = client.post("/api/admin/users", json=NEW_USER)

    assert response.status_code == 422
    assert response.json() == {"detail": "email_taken"}


def test_any_other_creation_error_is_still_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = SupabaseAdminError("Supabase Admin API error 500: boom")
    client = _client_with(AdminUserService(FakeUserRepository(), _RejectingSupabaseAdminClient(rejection)), monkeypatch)

    response = client.post("/api/admin/users", json=NEW_USER)

    assert response.status_code == 500
    assert "boom" not in response.text


def test_the_sqlalchemy_repository_finds_the_email_ignoring_case() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add(Role(id=1, name="standard"))
        db.add(User(id=uuid.uuid4(), email="Ana@RedSana.dev", role_id=1))
        db.commit()
        repository = SqlAlchemyUserRepository(db)

        assert repository.get_by_email("ana@redsana.dev") is not None
        assert repository.get_by_email("otra@redsana.dev") is None
    finally:
        db.close()
        Base.metadata.drop_all(engine)
