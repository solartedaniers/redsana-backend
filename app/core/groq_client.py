import json
import urllib.error
import urllib.request

from app.core.config import Settings, get_settings

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClientError(Exception):
    pass


def get_groq_client() -> "GroqClient":
    # Dependencia FastAPI separada del constructor para poder overridearla
    # en tests (mismo patron que get_db), sin pegarle a la API real de Groq.
    return GroqClient(get_settings())


class GroqClient:
    """Unica clase que sabe hablar HTTP con la API de Groq (urllib, sin
    dependencia nueva: httpx en requirements.txt esta mal declarado y no
    esta instalado). El resto del dominio no conoce el detalle HTTP."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model

    def chat(self, system_prompt: str, user_message: str) -> str:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        request = urllib.request.Request(
            url=GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # Cloudflare (delante de la API de Groq) devuelve 403 sin un
                # User-Agent "de navegador real": el default de urllib lo dispara.
                "User-Agent": "Mozilla/5.0 (compatible; RedSana-backend/1.0)",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            raise GroqClientError(f"Groq API error {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise GroqClientError(f"no se pudo contactar a Groq: {error.reason}") from error

        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as error:
            raise GroqClientError(f"respuesta de Groq con forma inesperada: {payload}") from error
