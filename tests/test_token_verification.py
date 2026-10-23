"""decode_supabase_token con claves ES256 generadas aquí y un JWKS simulado (sin red): qué tokens acepta y cuántas veces
consulta el JWKS cuando llega un kid que no conoce."""
import base64
import hashlib
import hmac
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jose import jwk, jwt

from app.core import security
from app.core.config import get_settings

KID = "clave-actual"
NEW_KID = "clave-rotada"
NOW = 1_800_000_000.0


def _key_pair(kid: str) -> tuple[bytes, dict]:
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, {**jwk.construct(public_pem, "ES256").to_dict(), "kid": kid, "alg": "ES256"}


PRIVATE_PEM, PUBLIC_JWK = _key_pair(KID)
ROTATED_PRIVATE_PEM, ROTATED_PUBLIC_JWK = _key_pair(NEW_KID)


def _claims(**overrides) -> dict:
    return {"sub": "00000000-0000-4000-8000-000000000001", "aud": get_settings().supabase_jwt_audience,
            "exp": int(NOW) + 3600, **overrides}


def _token(private_pem: bytes = PRIVATE_PEM, kid: str | None = KID, **claims) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(_claims(**claims), private_pem, algorithm="ES256", headers=headers)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture()
def jwks(monkeypatch):
    """JWKS simulado: cuenta las consultas y permite cambiar sus claves (rotación) y la hora."""
    state = {"keys": [PUBLIC_JWK], "fetches": 0, "now": NOW}

    def fetch():
        state["fetches"] += 1
        return list(state["keys"])

    monkeypatch.setattr(security, "_fetch_jwks", fetch)
    monkeypatch.setattr(security.time, "time", lambda: state["now"])
    # Firmas y vencimiento se validan contra la hora simulada, igual que el caché.
    monkeypatch.setattr("jose.jwt.timegm", lambda _: int(state["now"]))
    monkeypatch.setattr(security, "_jwks_cache", {"keys": [], "fetched_at": 0.0, "unknown_kid_refreshed_at": 0.0})
    return state


def _rejected(token: str) -> bool:
    with pytest.raises(HTTPException) as error:
        security.decode_supabase_token(token)
    return error.value.status_code == 401


def test_a_valid_token_is_accepted(jwks) -> None:
    assert security.decode_supabase_token(_token())["sub"] == _claims()["sub"]


def test_a_token_for_another_audience_is_rejected(jwks) -> None:
    assert _rejected(_token(aud="otra-app"))


def test_an_expired_token_is_rejected(jwks) -> None:
    assert _rejected(_token(exp=int(NOW) - 60))


def test_an_hs256_token_forged_with_the_public_key_is_rejected(jwks) -> None:
    """El ataque de CVE-2026-85394: firmar con HMAC usando la clave pública como secreto. El algoritmo sale del JWKS."""
    public_pem = jwk.construct(PUBLIC_JWK, "ES256").to_pem()
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    signature = _b64(hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())

    assert _rejected(f"{header}.{payload}.{signature}")


def test_a_token_without_kid_is_401_not_a_server_error(jwks) -> None:
    assert _rejected(_token(kid=None))


def test_an_unknown_kid_refreshes_the_jwks_at_most_once_per_interval(jwks) -> None:
    security.decode_supabase_token(_token())
    assert jwks["fetches"] == 1

    assert _rejected(_token(kid="inventado-1"))
    assert jwks["fetches"] == 2
    # Dentro del intervalo, más kids inventados no vuelven a consultar a Supabase.
    for attempt in range(5):
        assert _rejected(_token(kid=f"inventado-{attempt + 2}"))
    assert jwks["fetches"] == 2

    jwks["now"] += get_settings().jwks_unknown_kid_refresh_seconds
    assert _rejected(_token(kid="inventado-tarde"))
    assert jwks["fetches"] == 3


def test_a_rotated_key_is_still_picked_up_on_the_first_request(jwks) -> None:
    security.decode_supabase_token(_token())
    jwks["keys"] = [PUBLIC_JWK, ROTATED_PUBLIC_JWK]

    claims = security.decode_supabase_token(_token(ROTATED_PRIVATE_PEM, kid=NEW_KID))

    assert claims["sub"] == _claims()["sub"]
    assert jwks["fetches"] == 2
