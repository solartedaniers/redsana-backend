import json
import urllib.error
import urllib.request
import uuid

from app.core.config import Settings


class SupabaseAdminError(Exception):
    pass


class SupabaseAdminClient:
    """Unica clase que sabe hablar con la Admin API de Supabase Auth (requiere
    el service_role key, nunca el anon key). El resto del dominio de admin
    no conoce el detalle HTTP de Supabase."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.supabase_url.rstrip("/")
        self._service_role_key = settings.supabase_service_role_key

    def invite_user(self, email: str, full_name: str | None) -> uuid.UUID:
        """Crea el usuario en Supabase Auth y le envia el correo de invitacion
        (el usuario define su propia contraseña, el admin nunca la conoce)."""
        body = {"email": email, "data": {"full_name": full_name}}
        response = self._request("POST", "/auth/v1/invite", body)
        return uuid.UUID(response["id"])

    def delete_user(self, user_id: uuid.UUID) -> None:
        try:
            self._request("DELETE", f"/auth/v1/admin/users/{user_id}", None)
        except SupabaseAdminError as error:
            if "404" not in str(error):
                raise

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "apikey": self._service_role_key,
                "Authorization": f"Bearer {self._service_role_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            raise SupabaseAdminError(f"Supabase Admin API error {error.code}: {detail}") from error
