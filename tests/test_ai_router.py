"""Sin base ni red: /api/ai/status y /api/ai/warm-up piden sesión, no tocan la base y nunca devuelven un error
 por una IA dormida."""
from fastapi.testclient import TestClient
from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway, AiUnavailableReason
from app.core.ai_composition import get_ai_gateway
from app.core.security import get_current_claims
from app.main import app

AUTH = {"Authorization": "Bearer fake"}


class _FakeGateway(AiGateway):
    def __init__(self, availability: AiAvailability, reason: AiUnavailableReason | None = None) -> None:
        self._availability = availability
        self._reason = reason
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

    def unavailable_reason(self) -> AiUnavailableReason | None:
        return self._reason

    def start_warm_up(self) -> None:
        self.warm_ups += 1
        self._availability, self._reason = "warming_up", None


def _client(gateway: AiGateway) -> TestClient:
    app.dependency_overrides[get_current_claims] = lambda: {"sub": "00000000-0000-0000-0000-000000000001"}
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    return TestClient(app)


def test_status_reports_each_availability():
    try:
        for availability in ("ready", "warming_up", "unavailable"):
            response = _client(_FakeGateway(availability)).get("/api/ai/status", headers=AUTH)

            assert response.status_code == 200
            assert response.json()["status"] == availability
    finally:
        app.dependency_overrides.clear()


def test_warm_up_restarts_a_finished_attempt_and_answers_without_waiting_for_it():
    gateway = _FakeGateway("unavailable", "timed_out")
    try:
        response = _client(gateway).post("/api/ai/warm-up", headers=AUTH)

        assert response.status_code == 202
        # El calentamiento sigue en su propio hilo: la respuesta trae el estado recién iniciado.
        assert response.json() == {"status": "warming_up", "reason": None}
        assert gateway.warm_ups == 1
    finally:
        app.dependency_overrides.clear()


def test_status_explains_why_the_ai_is_unavailable():
    try:
        response = _client(_FakeGateway("unavailable", "service_error")).get("/api/ai/status", headers=AUTH)

        assert response.json() == {"status": "unavailable", "reason": "service_error"}
    finally:
        app.dependency_overrides.clear()


def test_status_does_not_start_a_warm_up():
    gateway = _FakeGateway("warming_up")
    try:
        _client(gateway).get("/api/ai/status", headers=AUTH)

        assert gateway.warm_ups == 0
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

        assert response.json() == {"status": "ready", "reason": None}
    finally:
        app.dependency_overrides.clear()
