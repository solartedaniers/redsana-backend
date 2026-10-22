"""Sin red: urlopen falso para comprobar timeout, reintentos limitados y errores tipados del cliente."""
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from app.ai_gateway.ai_service_client import API_KEY_HEADER, AiServiceClient
from app.ai_gateway.ai_service_errors import (
    AiServiceChatEngineError,
    AiServiceError,
    AiServiceRejectedError,
    AiServiceResponseError,
    AiServiceUnavailableError,
)
from redsana_ai import ChatEngineError

_BASE_URL = "https://ai.example.invalid/"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _json(payload: object) -> _Response:
    return _Response(json.dumps(payload).encode())


def _http_error(status: int, body: object | None = None, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    raw = json.dumps(body).encode() if body is not None else b"<html>Service Unavailable</html>"
    return urllib.error.HTTPError(_BASE_URL, status, "error", headers or {}, io.BytesIO(raw))


def _client(sleeps: list[float] | None = None, max_retries: int = 2) -> AiServiceClient:
    return AiServiceClient(
        base_url=_BASE_URL,
        api_key="test-shared-key",
        timeout_seconds=9,
        max_retries=max_retries,
        retry_backoff_seconds=0.5,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_post_sends_json_with_the_key_and_the_configured_timeout() -> None:
    with patch("urllib.request.urlopen", return_value=_json({"reply": "hola"})) as urlopen:
        payload = _client().post("/v1/chat", {"user_message": "hola"})

    request = urlopen.call_args.args[0]
    assert payload == {"reply": "hola"}
    assert request.full_url == "https://ai.example.invalid/v1/chat"
    assert request.get_method() == "POST"
    assert request.get_header(API_KEY_HEADER.capitalize()) == "test-shared-key"
    assert json.loads(request.data) == {"user_message": "hola"}
    assert urlopen.call_args.kwargs["timeout"] == 9


def test_health_does_not_send_the_key_and_uses_its_own_timeout() -> None:
    with patch("urllib.request.urlopen", return_value=_json({"status": "ok", "ready": True})) as urlopen:
        ready = _client().health(timeout_seconds=3)

    request = urlopen.call_args.args[0]
    assert ready is True
    assert request.get_header(API_KEY_HEADER.capitalize()) is None
    assert urlopen.call_args.kwargs["timeout"] == 3


def test_health_reports_not_ready_while_the_service_warms_up() -> None:
    with patch("urllib.request.urlopen", return_value=_json({"status": "ok", "ready": False})):
        assert _client().health(timeout_seconds=3) is False


def test_a_refused_connection_is_retried_with_growing_waits_then_reported_unavailable() -> None:
    sleeps: list[float] = []
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(ConnectionRefusedError())) as urlopen:
        with pytest.raises(AiServiceUnavailableError):
            _client(sleeps).post("/v1/chat", {})

    assert urlopen.call_count == 3
    assert sleeps == [0.5, 1.0]


def test_a_proxy_503_without_the_service_body_is_retried_and_can_recover() -> None:
    responses = [_http_error(503), _json({"reply": "ok"})]
    with patch("urllib.request.urlopen", side_effect=responses) as urlopen:
        payload = _client().post("/v1/chat", {})

    assert payload == {"reply": "ok"}
    assert urlopen.call_count == 2


def test_a_timeout_is_not_retried() -> None:
    with patch("urllib.request.urlopen", side_effect=TimeoutError()) as urlopen:
        with pytest.raises(AiServiceUnavailableError):
            _client().post("/v1/chat", {})

    assert urlopen.call_count == 1


def test_a_timeout_wrapped_by_urllib_is_not_retried_either() -> None:
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError())) as urlopen:
        with pytest.raises(AiServiceUnavailableError):
            _client().post("/v1/chat", {})

    assert urlopen.call_count == 1


def test_the_service_chat_engine_failure_keeps_its_own_type() -> None:
    error = _http_error(502, {"code": "chat_engine_unavailable", "message": "chat engine unavailable"})
    with patch("urllib.request.urlopen", side_effect=error) as urlopen:
        with pytest.raises(AiServiceChatEngineError):
            _client().post("/v1/chat", {})

    assert urlopen.call_count == 1


def test_a_rejected_key_is_not_retried() -> None:
    error = _http_error(401, {"code": "invalid_api_key", "message": "missing or invalid API key"})
    with patch("urllib.request.urlopen", side_effect=error) as urlopen:
        with pytest.raises(AiServiceRejectedError):
            _client().post("/v1/chat", {})

    assert urlopen.call_count == 1


def test_an_internal_service_error_is_a_response_error() -> None:
    with patch("urllib.request.urlopen", side_effect=_http_error(500, {"code": "internal_error", "message": "x"})):
        with pytest.raises(AiServiceResponseError):
            _client().post("/v1/chat", {})


def test_a_body_that_is_not_json_is_a_response_error() -> None:
    with patch("urllib.request.urlopen", return_value=_Response(b"<html>")):
        with pytest.raises(AiServiceResponseError):
            _client().post("/v1/chat", {})


def test_every_service_error_is_a_chat_engine_error() -> None:
    # Así el chat sigue respondiendo 502 como cuando Groq falla en modo local.
    assert issubclass(AiServiceError, ChatEngineError)


def test_a_render_429_while_waking_is_unavailable_not_rejected_and_keeps_retry_after() -> None:
    error = _http_error(429, headers={"Retry-After": "20", "x-render-routing": "hibernate-wake"})
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(AiServiceUnavailableError) as raised:
            _client(max_retries=0).health(timeout_seconds=3)

    assert raised.value.retry_after_seconds == 20
    # Lo que respondió Render queda en el mensaje para verlo en los logs.
    assert "429" in str(raised.value)
    assert "hibernate-wake" in str(raised.value)
    assert "Service Unavailable" in str(raised.value)


def test_a_retry_after_given_as_a_date_is_ignored() -> None:
    error = _http_error(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(AiServiceUnavailableError) as raised:
            _client(max_retries=0).health(timeout_seconds=3)

    assert raised.value.retry_after_seconds is None


def test_a_wrong_path_is_rejected_at_once_with_what_the_service_said() -> None:
    with patch("urllib.request.urlopen", side_effect=_http_error(404, {"detail": "Not Found"})) as urlopen:
        with pytest.raises(AiServiceRejectedError) as raised:
            _client().health(timeout_seconds=3)

    assert urlopen.call_count == 1
    assert "Not Found" in str(raised.value)


def test_a_render_429_hibernate_rate_limited_is_flagged() -> None:
    error = _http_error(429, headers={"x-render-routing": "hibernate-rate-limited"})
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(AiServiceUnavailableError) as raised:
            _client(max_retries=0).health(timeout_seconds=3)

    assert raised.value.rate_limited is True


def test_other_proxy_answers_are_not_flagged_as_rate_limited() -> None:
    error = _http_error(502, headers={"x-render-routing": "no-deploy"})
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(AiServiceUnavailableError) as raised:
            _client(max_retries=0).health(timeout_seconds=3)

    assert raised.value.rate_limited is False
