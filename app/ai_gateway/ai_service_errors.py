from redsana_ai import ChatEngineError


class AiServiceError(ChatEngineError):
    """El servicio de IA no pudo responder. Hereda de ChatEngineError para que el chat lo trate como hoy a Groq."""


class AiServiceUnavailableError(AiServiceError):
    """Dormido, encendiendo o inalcanzable: al usuario se le muestra "encendiendo", nunca un error."""

    def __init__(self, message: str, retry_after_seconds: float | None = None, rate_limited: bool = False) -> None:
        super().__init__(message)
        # Lo que pidió esperar el proxy (Retry-After); el calentamiento lo respeta antes de volver a consultar.
        self.retry_after_seconds = retry_after_seconds
        # Render frena las peticiones a un servicio que despierta: insistir seguido solo alarga el bloqueo.
        self.rate_limited = rate_limited


class AiServiceChatEngineError(AiServiceError):
    """El servicio está despierto pero su motor (Groq) falló: igual que un fallo de Groq en modo local."""


class AiServiceRejectedError(AiServiceError):
    """El servicio rechazó la petición (clave o datos): es un problema de configuración o de código, no de red."""


class AiServiceResponseError(AiServiceError):
    """El servicio falló por dentro o respondió algo que no se puede leer."""
