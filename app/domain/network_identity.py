import hashlib
import hmac
import uuid


class NetworkIdentifier:
    """Convierte el SHA-256 de la MAC del router en un HMAC con secreto y dueño. Un SHA-256 de una MAC se revierte
     por fuerza bruta en segundos; el HMAC lo impide y además no deja cruzar el mismo router entre usuarios."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def network_id(self, owner_id: uuid.UUID, client_fingerprint: str | None) -> str | None:
        if client_fingerprint is None:
            return None
        message = f"{owner_id}:{client_fingerprint}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()
