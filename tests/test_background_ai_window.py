"""De punta a punta con SQLite y AI_MODE=remote: cada medición evalúa en segundo plano, pero solo llama al servicio
de IA dentro de la ventana de uso interactivo. Fuera de ella no hay ninguna petición que lo despierte."""

import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient
from test_network_metrics_router import SNAPSHOT_PAYLOAD, client  # noqa: F401 (fixture)

from app.core import ai_composition
from app.core.config import Settings

AUTH = {"Authorization": "Bearer fake"}


@pytest.fixture
def remote_mode(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Pone el backend en modo remoto y registra cada URL que se intente abrir (el servicio "no contesta")."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg2://test:test@127.0.0.1:1/test",
        supabase_url="https://example.invalid",
        supabase_service_role_key="test-service-role-key",
        network_id_secret="test-network-id-secret",
        ai_mode="remote",
        ai_service_url="https://ai.example.invalid",
        ai_service_api_key="test-key",
        ai_service_max_retries=0,
    )
    monkeypatch.setattr(ai_composition, "get_settings", lambda: settings)
    ai_composition._remote_ai_gateway.cache_clear()
    opened: list[str] = []

    def refuse(request: urllib.request.Request, timeout: float):
        opened.append(request.full_url)
        raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    yield opened
    ai_composition._remote_ai_gateway.cache_clear()


def test_measurements_outside_the_window_never_call_the_ai_service(client: TestClient, remote_mode: list[str]) -> None:
    for _ in range(3):
        assert client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers=AUTH).status_code == 201

    assert remote_mode == []


def test_measurements_inside_the_window_use_the_service_and_fall_back_locally(
    client: TestClient, remote_mode: list[str]
) -> None:
    # Un uso interactivo (aquí, el chat o el calentamiento) abre la ventana.
    ai_composition._remote_ai_gateway()._usage_window.record_use()

    response = client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers=AUTH)

    assert response.status_code == 201
    assert "https://ai.example.invalid/v1/outage/detect" in remote_mode


def test_background_calls_do_not_open_the_window(client: TestClient, remote_mode: list[str]) -> None:
    client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers=AUTH)

    assert ai_composition._remote_ai_gateway()._usage_window.is_open() is False
