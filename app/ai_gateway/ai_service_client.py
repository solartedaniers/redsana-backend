import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.ai_gateway.ai_service_errors import (
    AiServiceChatEngineError,
    AiServiceRejectedError,
    AiServiceResponseError,
    AiServiceUnavailableError,
)

# Nombre del encabezado acordado con redsana_ai_service; el valor de la clave vive solo en el entorno.
API_KEY_HEADER = "X-AI-Service-Key"
# Lo que devuelve el proxy de Render mientras el servicio arranca o se reinicia (sin el cuerpo tipado del servicio).
_PROXY_UNAVAILABLE_STATUSES = frozenset({502, 503, 504})
_CHAT_ENGINE_UNAVAILABLE_CODE = "chat_engine_unavailable"


class _RetryableError(Exception):
    """Fallo que vale la pena reintentar: conexión rechazada o el proxy diciendo que el servicio aún no está."""


class AiServiceClient:
    """Única clase que habla HTTP con el servicio de IA (urllib de la stdlib, como GroqClient)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep

    def health(self, timeout_seconds: float) -> bool:
        """True si el servicio respondió y ya terminó de calentar."""
        payload = self._request("GET", "/health", None, timeout_seconds, authenticated=False)
        return payload.get("ready") is True

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body, self._timeout_seconds, authenticated=True)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, timeout_seconds: float, authenticated: bool
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return self._send(method, path, body, timeout_seconds, authenticated)
            except _RetryableError as error:
                if attempt >= self._max_retries:
                    raise AiServiceUnavailableError(f"AI service unavailable after {attempt + 1} attempts: {error}") from error
                # Espera creciente y con tope en max_retries: insistir sin pausa solo cargaría un servicio que arranca.
                self._sleep(self._retry_backoff_seconds * 2**attempt)
                attempt += 1

    def _send(
        self, method: str, path: str, body: dict[str, Any] | None, timeout_seconds: float, authenticated: bool
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers[API_KEY_HEADER] = self._api_key
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise _http_error(error) from error
        except TimeoutError as error:
            # No reintento un timeout: ya esperé timeout_seconds y repetirlo solo multiplicaría la espera del usuario.
            raise AiServiceUnavailableError(f"AI service did not answer in {timeout_seconds}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise AiServiceUnavailableError(f"AI service did not answer in {timeout_seconds}s") from error
            raise _RetryableError(f"could not reach the AI service: {error.reason}") from error
        except ConnectionError as error:
            raise _RetryableError(f"connection to the AI service failed: {error}") from error

        try:
            return json.loads(raw)
        except ValueError as error:
            raise AiServiceResponseError("AI service returned a body that is not JSON") from error


def _service_error_code(error: urllib.error.HTTPError) -> str | None:
    try:
        payload = json.loads(error.read())
    except ValueError:
        return None
    return payload.get("code") if isinstance(payload, dict) else None


def _http_error(error: urllib.error.HTTPError) -> Exception:
    code = _service_error_code(error)
    if code == _CHAT_ENGINE_UNAVAILABLE_CODE:
        return AiServiceChatEngineError("AI service chat engine unavailable")
    if code is None and error.code in _PROXY_UNAVAILABLE_STATUSES:
        return _RetryableError(f"AI service proxy answered {error.code}")
    if 400 <= error.code < 500:
        return AiServiceRejectedError(f"AI service rejected the request: {error.code} {code}")
    return AiServiceResponseError(f"AI service failed: {error.code} {code}")
