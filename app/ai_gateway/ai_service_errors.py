from redsana_ai import ChatEngineError


class AiServiceError(ChatEngineError):
    """El servicio de IA no pudo responder. Hereda de ChatEngineError para que el chat lo trate como hoy a Groq."""


class AiServiceUnavailableError(AiServiceError):
    """Dormido, encendiendo o inalcanzable: al usuario se le muestra "encendiendo", nunca un error."""


class AiServiceChatEngineError(AiServiceError):
    """El servicio está despierto pero su motor (Groq) falló: igual que un fallo de Groq en modo local."""


class AiServiceRejectedError(AiServiceError):
    """El servicio rechazó la petición (clave o datos): es un problema de configuración o de código, no de red."""


class AiServiceResponseError(AiServiceError):
    """El servicio falló por dentro o respondió algo que no se puede leer."""
