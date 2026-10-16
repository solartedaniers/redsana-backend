"""Sin red: el gateway remoto traduce el /health del servicio a lista/encendiendo/no disponible y calienta sin
 lanzar errores; los detectores respetan la ventana de uso interactivo."""
from redsana_ai import IsolationForestAnomalyDetector, StreakOutageDetector

from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.ai_service_errors import AiServiceRejectedError, AiServiceUnavailableError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_adapters import RemoteSecurityBriefing, RemoteSecurityChat
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector


class _FakeStatusClient(AiServiceClient):
    """Devuelve, en orden, lo que diría /health en cada consulta (un bool o una excepción)."""

    def __init__(self, *answers: object) -> None:
        super().__init__("https://ai.example.invalid", "test-key", 5, max_retries=0, retry_backoff_seconds=0)
        self._answers = list(answers)
        self.calls = 0
        self.timeouts: list[float] = []

    def health(self, timeout_seconds: float) -> bool:
        self.calls += 1
        self.timeouts.append(timeout_seconds)
        answer = self._answers[min(self.calls, len(self._answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return bool(answer)


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _gateway(status_client: AiServiceClient, window: InteractiveUsageWindow | None = None, fake_time: _FakeTime | None = None) -> RemoteAiGateway:
    fake_time = fake_time or _FakeTime()
    return RemoteAiGateway(
        client=AiServiceClient("https://ai.example.invalid", "test-key", 5, max_retries=0, retry_backoff_seconds=0),
        status_client=status_client,
        local_fallback=LocalAiGateway(lambda: None),
        usage_window=window or InteractiveUsageWindow(600),
        status_timeout_seconds=5,
        warm_up_timeout_seconds=90,
        warm_up_probe_timeout_seconds=30,
        warm_up_poll_seconds=2,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
    )


def test_status_is_ready_when_the_service_finished_warming_up() -> None:
    assert _gateway(_FakeStatusClient(True)).status() == "ready"


def test_status_is_warming_up_while_the_service_warms_up() -> None:
    assert _gateway(_FakeStatusClient(False)).status() == "warming_up"


def test_a_sleeping_service_is_warming_up_and_not_an_error() -> None:
    assert _gateway(_FakeStatusClient(AiServiceUnavailableError("asleep"))).status() == "warming_up"


def test_a_rejected_key_is_unavailable() -> None:
    assert _gateway(_FakeStatusClient(AiServiceRejectedError("401"))).status() == "unavailable"


def test_warm_up_polls_until_the_service_is_ready_and_opens_the_window() -> None:
    status_client = _FakeStatusClient(AiServiceUnavailableError("asleep"), False, True)
    window = InteractiveUsageWindow(600)
    fake_time = _FakeTime()

    _gateway(status_client, window, fake_time).warm_up()

    assert status_client.calls == 3
    assert fake_time.sleeps == [2, 2]
    assert window.is_open() is True


def test_warm_up_gives_up_after_its_timeout_without_raising() -> None:
    status_client = _FakeStatusClient(AiServiceUnavailableError("asleep"))
    fake_time = _FakeTime()

    _gateway(status_client, fake_time=fake_time).warm_up()

    assert fake_time.now >= 90
    assert len(fake_time.sleeps) == 45


def test_warm_up_keeps_each_probe_open_without_passing_its_cap_and_logs_it(caplog) -> None:
    status_client = _FakeStatusClient(AiServiceUnavailableError("asleep"))
    gateway = _gateway(status_client)

    with caplog.at_level("INFO", logger="app.ai_gateway.remote_ai_gateway"):
        gateway.warm_up()
    gateway.status()

    assert status_client.timeouts[0] == 30
    assert status_client.timeouts[-2] == 5  # a 2 s del tope no abro otra espera de 30 s
    assert status_client.timeouts[-1] == 5  # el estado normal sigue siendo corto
    assert "AI warm-up probe 1: warming_up" in caplog.text
    assert "AI warm-up finished: warming_up after 46 probes" in caplog.text


def test_warm_up_stops_at_once_if_the_service_is_misconfigured() -> None:
    status_client = _FakeStatusClient(AiServiceRejectedError("401"))
    fake_time = _FakeTime()

    _gateway(status_client, fake_time=fake_time).warm_up()

    assert status_client.calls == 1
    assert fake_time.sleeps == []


def test_a_concurrent_warm_up_does_not_poll_twice() -> None:
    status_client = _FakeStatusClient(True)
    gateway = _gateway(status_client)
    gateway._warm_up_lock.acquire()

    gateway.warm_up()

    assert status_client.calls == 0


def test_chat_and_briefing_always_go_to_the_service() -> None:
    gateway = _gateway(_FakeStatusClient(True))

    assert isinstance(gateway.security_chat(), RemoteSecurityChat)
    assert isinstance(gateway.security_briefing(), RemoteSecurityBriefing)


def test_detectors_are_windowed_over_the_local_package() -> None:
    gateway = _gateway(_FakeStatusClient(True))

    anomaly, outage = gateway.anomaly_detector(), gateway.outage_detector()

    assert isinstance(anomaly, WindowedAnomalyDetector)
    assert isinstance(anomaly._local, IsolationForestAnomalyDetector)
    assert isinstance(outage, WindowedOutageDetector)
    assert isinstance(outage._local, StreakOutageDetector)
