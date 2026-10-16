"""Sin base ni red: /api/ai/status y /api/ai/warm-up piden sesión, no tocan la base y nunca devuelven un error
 por una IA dormida."""
from fastapi.testclient import TestClient
from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway
from app.core.ai_composition import get_ai_gateway
from app.core.security import get_current_claims
from app.main import app

AUTH = {"Authorization": "Bearer fake"}


class _FakeGateway(AiGateway):
    def __init__(self, availability: AiAvailability) -> None:
        self._availability = availability
        self.warm_ups = 0

    def security_chat(self) -> SecurityChat:
        raise AssertionError("not used")

    def security_briefing(self) -> SecurityBriefing:
        raise AssertionError("not used")

    def anomaly_detector(self) -> AnomalyDetector:
        raise AssertionError("not used")

    def outage_detector(self) -> OutageDetector:
        raise AssertionError("not used")

    def status(self) -> AiAvailability:
        return self._availability

    def warm_up(self) -> None:
        self.warm_ups += 1
        self._availability = "ready"


def _client(gateway: AiGateway) -> TestClient:
    app.dependency_overrides[get_current_claims] = lambda: {"sub": "00000000-0000-0000-0000-000000000001"}
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    return TestClient(app)


def test_status_reports_each_availability():
    try:
        for availability in ("ready", "warming_up", "unavailable"):
            response = _client(_FakeGateway(availability)).get("/api/ai/status", headers=AUTH)

            assert response.status_code == 200
            assert response.json() == {"status": availability}
    finally:
        app.dependency_overrides.clear()


def test_warm_up_is_accepted_and_runs_after_answering():
    gateway = _FakeGateway("warming_up")
    try:
        response = _client(gateway).post("/api/ai/warm-up", headers=AUTH)

        assert response.status_code == 202
        # Responde con el estado de ese momento; el calentamiento corre después de la respuesta.
        assert response.json() == {"status": "warming_up"}
        assert gateway.warm_ups == 1
    finally:
        app.dependency_overrides.clear()


def test_both_endpoints_require_a_session():
    app.dependency_overrides[get_ai_gateway] = lambda: _FakeGateway("ready")
    try:
        client = TestClient(app)

        assert client.get("/api/ai/status").status_code in (401, 403)
        assert client.post("/api/ai/warm-up").status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


def test_local_mode_is_always_ready():
    app.dependency_overrides[get_current_claims] = lambda: {"sub": "00000000-0000-0000-0000-000000000001"}
    try:
        response = TestClient(app).get("/api/ai/status", headers=AUTH)

        assert response.json() == {"status": "ready"}
    finally:
        app.dependency_overrides.clear()
