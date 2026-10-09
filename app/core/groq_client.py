import json
import urllib.error
import urllib.request

from app.core.chat_engine import ChatEngine, ChatEngineError, ChatTurn
from app.core.config import Settings, get_settings

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClientError(ChatEngineError):
    pass


def get_chat_engine() -> ChatEngine:
    # Va separada del constructor para poder reemplazarla en las pruebas sin llamar a la API real de Groq.
    return GroqClient(get_settings())


class GroqClient(ChatEngine):
    """Única clase que habla HTTP con Groq (con urllib de la stdlib); el resto del dominio no conoce ese detalle."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model
        self._timeout_seconds = settings.groq_timeout_seconds
        self._temperature = settings.groq_temperature

    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        body = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [{"role": "system", "content": system_prompt}]
            + [{"role": turn.role, "content": turn.content} for turn in turns],
        }
        request = urllib.request.Request(
            url=GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # Cloudflare, delante de Groq, devuelve 403 con el User-Agent por defecto de urllib.
                "User-Agent": "Mozilla/5.0 (compatible; RedSana-backend/1.0)",
            },
        )
        try:
            # Sin timeout, un Groq colgado dejaba abierta la petición del usuario indefinidamente.
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            raise GroqClientError(f"Groq API error {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise GroqClientError(f"no se pudo contactar a Groq: {error.reason}") from error
        except TimeoutError as error:
            raise GroqClientError(f"Groq no respondió en {self._timeout_seconds}s") from error

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as error:
            raise GroqClientError(f"respuesta de Groq con forma inesperada: {payload}") from error
