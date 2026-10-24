"""Sin base ni red: la ventana se abre con un uso interactivo y se cierra sola al pasar su duración."""

from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_window_starts_closed() -> None:
    assert InteractiveUsageWindow(600, _FakeClock()).is_open() is False


def test_an_interactive_use_opens_the_window_for_its_duration() -> None:
    clock = _FakeClock()
    window = InteractiveUsageWindow(600, clock)

    window.record_use()
    clock.now += 600

    assert window.is_open() is True


def test_the_window_closes_once_the_duration_passes() -> None:
    clock = _FakeClock()
    window = InteractiveUsageWindow(600, clock)

    window.record_use()
    clock.now += 601

    assert window.is_open() is False


def test_a_new_interactive_use_extends_the_window() -> None:
    clock = _FakeClock()
    window = InteractiveUsageWindow(600, clock)

    window.record_use()
    clock.now += 500
    window.record_use()
    clock.now += 500

    assert window.is_open() is True


def test_checking_the_window_does_not_renew_it() -> None:
    clock = _FakeClock()
    window = InteractiveUsageWindow(600, clock)

    window.record_use()
    for _ in range(10):
        clock.now += 100
        window.is_open()

    assert window.is_open() is False
