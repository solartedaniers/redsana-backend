import json
import time
import urllib.request
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import get_settings

_bearer_scheme = HTTPBearer()

_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0}


def _fetch_jwks() -> list[dict[str, Any]]:
    settings = get_settings()
    with urllib.request.urlopen(settings.supabase_jwks_url) as response:
        return json.load(response)["keys"]


def _get_signing_key(kid: str) -> dict[str, Any]:
    """Busca la clave en el JWKS cacheado; si no aparece (rotacion de claves), refresca una vez."""
    settings = get_settings()
    now = time.time()
    if not _jwks_cache["keys"] or (now - _jwks_cache["fetched_at"]) > settings.jwks_cache_ttl_seconds:
        _jwks_cache["keys"] = _fetch_jwks()
        _jwks_cache["fetched_at"] = now

    key = next((k for k in _jwks_cache["keys"] if k.get("kid") == kid), None)
    if key is None:
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
        signing_key = _get_signing_key(unverified_header["kid"])
        return jwt.decode(
            token,
            signing_key,
            algorithms=[signing_key.get("alg", "ES256")],
            audience=settings.supabase_jwt_audience,
        )
    except JWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from error


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Dependency de FastAPI: valida el Bearer token y devuelve los claims del JWT de Supabase."""
    return decode_supabase_token(credentials.credentials)
