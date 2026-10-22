"""Sin red: el gateway remoto traduce el /health del servicio a lista/encendiendo/no disponible, mantiene ese estado en
 memoria con un único calentamiento en segundo plano y los detectores respetan la ventana de uso interactivo."""
from collections.abc import Callable

from redsana_ai import IsolationForestAnomalyDetector, StreakOutageDetector

from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.ai_service_errors import AiServiceRejectedError, AiServiceUnavailableError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_adapters import RemoteSecurityBriefing, RemoteSecurityChat
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway, WarmUpSchedule
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector

_SCHEDULE = WarmUpSchedule(
    timeout_seconds=300, probe_timeout_seconds=90, backoff_seconds=5, max_backoff_seconds=15, backoff_factor=1.5
)
_ASLEEP = AiServiceUnavailableError("proxy answered 429")


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeStatusClient(AiServiceClient):
    """Devuelve, en orden, lo que diría /health en cada consulta (un bool o una excepción); la última se repite."""

    def __init__(self, *answers: object, fake_time: _FakeTime | None = None, seconds_per_probe: float = 0) -> None:
        super().__init__("https://ai.example.invalid", "test-key", 5, max_retries=0, retry_backoff_seconds=0)
        self._answers = list(answers)
        self._fake_time = fake_time
        self._seconds_per_probe = seconds_per_probe
        self.calls = 0
        self.timeouts: list[float] = []

    def health(self, timeout_seconds: float) -> bool:
        self.calls += 1
        self.timeouts.append(timeout_seconds)
        if self._fake_time is not None:
            self._fake_time.now += self._seconds_per_probe
        answer = self._answers[min(self.calls, len(self._answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return bool(answer)


class _Threads:
    """Arranca el calentamiento en el acto (run_now) o lo deja pendiente para simular uno en curso."""

    def __init__(self, run_now: bool = True) -> None:
        self._run_now = run_now
        self.started: list[Callable[[], None]] = []

    def start(self, target: Callable[[], None]) -> None:
        self.started.append(target)
        if self._run_now:
            target()


def _gateway(
    status_client: AiServiceClient,
    fake_time: _FakeTime | None = None,
    window: InteractiveUsageWindow | None = None,
    threads: _Threads | None = None,
) -> RemoteAiGateway:
    fake_time = fake_time or _FakeTime()
    return RemoteAiGateway(
        client=AiServiceClient("https://ai.example.invalid", "test-key", 5, max_retries=0, retry_backoff_seconds=0),
        status_client=status_client,
        local_fallback=LocalAiGateway(lambda: None),
        usage_window=window or InteractiveUsageWindow(600, clock=fake_time.clock),
        status_timeout_seconds=5,
        status_cache_seconds=5,
        warm_up_schedule=_SCHEDULE,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        start_thread=(threads or _Threads()).start,
    )


def test_status_is_ready_when_the_service_finished_warming_up() -> None:
    assert _gateway(_FakeStatusClient(True)).status() == "ready"


def test_status_is_warming_up_while_the_service_warms_up() -> None:
    assert _gateway(_FakeStatusClient(False)).status() == "warming_up"


def test_a_sleeping_service_is_warming_up_and_not_an_error() -> None:
    assert _gateway(_FakeStatusClient(_ASLEEP)).status() == "warming_up"


def test_a_rejected_key_is_unavailable_with_its_reason() -> None:
    gateway = _gateway(_FakeStatusClient(AiServiceRejectedError("401")))

    assert gateway.status() == "unavailable"
    assert gateway.unavailable_reason() == "service_error"


def test_status_reads_memory_while_a_warm_up_runs() -> None:
    status_client = _FakeStatusClient(True)
    gateway = _gateway(status_client, threads=_Threads(run_now=False))

    gateway.start_warm_up()

    assert gateway.status() == "warming_up"
    assert gateway.status() == "warming_up"
    assert status_client.calls == 0


def test_status_reuses_its_last_answer_for_a_few_seconds() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(True)
    gateway = _gateway(status_client, fake_time)

    gateway.status()
    fake_time.now += 4
    gateway.status()
    assert status_client.calls == 1

    fake_time.now += 2
    gateway.status()
    assert status_client.calls == 2


def test_warm_up_waits_patiently_then_backs_off_until_ready_and_opens_the_window() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(_ASLEEP, _ASLEEP, True)
    window = InteractiveUsageWindow(600, clock=fake_time.clock)

    _gateway(status_client, fake_time, window).start_warm_up()

    assert status_client.timeouts[0] == 90
    assert fake_time.sleeps == [5, 7.5]
    assert window.is_open() is True


def test_a_429_from_render_does_not_end_the_warm_up() -> None:
    status_client = _FakeStatusClient(AiServiceUnavailableError("proxy answered 429"), True)
    gateway = _gateway(status_client)

    gateway.start_warm_up()

    assert gateway.status() == "ready"


def test_warm_up_respects_retry_after() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(AiServiceUnavailableError("429", retry_after_seconds=20), True)

    _gateway(status_client, fake_time).start_warm_up()

    assert fake_time.sleeps == [20]


def test_warm_up_gives_up_at_its_deadline_as_timed_out_with_a_capped_backoff(caplog) -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(_ASLEEP, fake_time=fake_time, seconds_per_probe=1)
    window = InteractiveUsageWindow(600, clock=fake_time.clock)
    gateway = _gateway(status_client, fake_time, window)

    with caplog.at_level("INFO", logger="app.ai_gateway.remote_ai_gateway"):
        gateway.start_warm_up()

    assert 300 <= fake_time.now <= 301
    assert max(fake_time.sleeps) == 15
    assert gateway.status() == "unavailable"
    assert gateway.unavailable_reason() == "timed_out"
    assert window.is_open() is False
    assert "AI warm-up probe 1: warming_up" in caplog.text
    assert "proxy answered 429" in caplog.text
    assert "AI warm-up finished: unavailable (timed_out)" in caplog.text


def test_a_timed_out_warm_up_stays_unavailable_until_someone_retries() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(_ASLEEP, fake_time=fake_time, seconds_per_probe=1)
    gateway = _gateway(status_client, fake_time)
    gateway.start_warm_up()
    calls = status_client.calls

    fake_time.now += 60
    assert gateway.status() == "unavailable"
    assert gateway.unavailable_reason() == "timed_out"
    assert status_client.calls == calls


def test_no_probe_waits_past_the_deadline() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(_ASLEEP, fake_time=fake_time, seconds_per_probe=80)

    _gateway(status_client, fake_time).start_warm_up()

    assert status_client.timeouts[0] == 90
    assert all(timeout <= 90 for timeout in status_client.timeouts)
    assert status_client.timeouts[-1] < 90


def test_warm_up_stops_at_once_if_the_service_is_misconfigured() -> None:
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(AiServiceRejectedError("404"))
    gateway = _gateway(status_client, fake_time)

    gateway.start_warm_up()

    assert status_client.calls == 1
    assert fake_time.sleeps == []
    assert gateway.unavailable_reason() == "service_error"


def test_a_running_warm_up_is_not_started_twice() -> None:
    threads = _Threads(run_now=False)
    gateway = _gateway(_FakeStatusClient(True), threads=threads)

    gateway.start_warm_up()
    gateway.start_warm_up()

    assert len(threads.started) == 1


def test_retry_after_a_finished_attempt_starts_a_new_one() -> None:
    threads = _Threads()
    status_client = _FakeStatusClient(AiServiceRejectedError("404"), True)
    gateway = _gateway(status_client, threads=threads)

    gateway.start_warm_up()
    gateway.start_warm_up()

    assert len(threads.started) == 2
    assert gateway.status() == "ready"


def test_an_ai_known_to_be_ready_is_not_warmed_up_again() -> None:
    threads = _Threads()
    status_client = _FakeStatusClient(True)
    gateway = _gateway(status_client, threads=threads)
    gateway.start_warm_up()

    gateway.start_warm_up()

    assert len(threads.started) == 1
    assert status_client.calls == 1


def test_a_stale_ready_is_confirmed_with_one_short_probe_before_warming_up() -> None:
    fake_time = _FakeTime()
    threads = _Threads()
    status_client = _FakeStatusClient(True, _ASLEEP, True)
    gateway = _gateway(status_client, fake_time, threads=threads)
    gateway.start_warm_up()
    fake_time.now += 600  # la IA pudo volver a dormirse

    gateway.start_warm_up()

    assert status_client.timeouts[1] == 5
    assert len(threads.started) == 2
    assert gateway.status() == "ready"


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
