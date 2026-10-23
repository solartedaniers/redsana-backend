import threading
import time
from collections.abc import Callable


class InteractiveUsageWindow:
    """Recuerda el último uso interactivo de la IA (calentamiento, chat o resumen) y dice si sigue abierta la ventana
     en que el servicio remoto probablemente está despierto. Solo los usos interactivos la renuevan."""

    def __init__(self, duration_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._duration_seconds = duration_seconds
        self._clock = clock
        self._last_use: float | None = None
        # Estado en memoria del proceso: con varios workers cada uno tendría su ventana (Render free usa uno).
        self._lock = threading.Lock()

    def record_use(self) -> None:
        with self._lock:
            self._last_use = self._clock()

    def is_open(self) -> bool:
        with self._lock:
            last_use = self._last_use
        return last_use is not None and self._clock() - last_use <= self._duration_seconds
