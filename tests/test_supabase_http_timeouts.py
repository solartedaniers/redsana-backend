"""Las llamadas a Supabase corren en el pool de hilos: sin timeout, un Supabase colgado lo agota."""
import io
import json
import urllib.error

import pytest

from app.core import security, supabase_admin_client
from app.core.config import get_settings
from app.core.supabase_admin_client import SupabaseAdminClient, SupabaseAdminError


def test_jwks_fetch_uses_the_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_urlopen(url, timeout=None):
        seen["timeout"] = timeout
        return io.BytesIO(json.dumps({"keys": []}).encode())

    monkeypatch.setattr(security.urllib.request, "urlopen", fake_urlopen)
    security._fetch_jwks()

    assert seen["timeout"] == get_settings().supabase_http_timeout_seconds


def test_admin_api_timeout_becomes_a_supabase_admin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def hanging_urlopen(request, timeout=None):
        seen["timeout"] = timeout
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(supabase_admin_client.urllib.request, "urlopen", hanging_urlopen)

    with pytest.raises(SupabaseAdminError):
        SupabaseAdminClient(get_settings())._request("GET", "/auth/v1/admin/users", None)
    assert seen["timeout"] == get_settings().supabase_http_timeout_seconds
