import json
import time
import uuid
import urllib.request
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.core.config import get_settings

_bearer_scheme = HTTPBearer()

# Supabase firma con ES256. Fijo aquí y no tomado del JWKS ni del token: así nadie elige el algoritmo.
_ALGORITHMS = ["ES256"]
_DECODE_OPTIONS = {
    "require": ["exp", "aud"],
    # PyJWT rechaza un iat en el futuro; python-jose no lo hacía. Con relojes un poco desfasados entre Supabase y
    # Render, eso dejaría fuera a quien acaba de iniciar sesión. Sí se exige que sea un número (ver abajo).
    "verify_iat": False,
}

_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0, "unknown_kid_refreshed_at": 0.0}


def _fetch_jwks() -> list[dict[str, Any]]:
    settings = get_settings()
    with urllib.request.urlopen(settings.supabase_jwks_url, timeout=settings.supabase_http_timeout_seconds) as response:
        return json.load(response)["keys"]


def _get_signing_key(kid: str | None) -> dict[str, Any]:
    """Busca la clave en el JWKS cacheado. Si no está (rotación de claves) lo refresca, pero como mucho una vez por
    intervalo: así un kid inventado no convierte cada petición en una consulta a Supabase."""
    settings = get_settings()
    now = time.time()
    if not _jwks_cache["keys"] or (now - _jwks_cache["fetched_at"]) > settings.jwks_cache_ttl_seconds:
        _jwks_cache["keys"] = _fetch_jwks()
        _jwks_cache["fetched_at"] = now

    key = next((k for k in _jwks_cache["keys"] if k.get("kid") == kid), None)
    if key is None and now - _jwks_cache["unknown_kid_refreshed_at"] >= settings.jwks_unknown_kid_refresh_seconds:
        _jwks_cache["unknown_kid_refreshed_at"] = now
        _jwks_cache["keys"] = _fetch_jwks()
        _jwks_cache["fetched_at"] = now
        key = next((k for k in _jwks_cache["keys"] if k.get("kid") == kid), None)

    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signing key not found")
    return key


def decode_supabase_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        unverified_header = jwt.get_unverified_header(token)
        signing_key = _get_signing_key(unverified_header.get("kid"))
        claims = jwt.decode(
            token,
            jwt.PyJWK(signing_key).key,
            algorithms=_ALGORITHMS,
            audience=settings.supabase_jwt_audience,
            options=_DECODE_OPTIONS,
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from error
    if not isinstance(claims.get("iat", 0), (int, float)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return claims


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Valida el Bearer token y devuelve los claims del JWT de Supabase."""
    return decode_supabase_token(credentials.credentials)


def owner_id_from_claims(claims: dict[str, Any]) -> uuid.UUID:
    """El dueño de los datos es el usuario del token (claim "sub")."""
    return uuid.UUID(claims["sub"])
