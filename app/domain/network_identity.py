import hashlib
import hmac
import uuid


class NetworkIdentifier:
    """Convierte la huella que manda el escritorio (SHA-256 de la MAC del router,
    calculado en el equipo: la MAC cruda nunca sale de él) en el identificador
    de red que se guarda: HMAC con un secreto del servidor y el owner.

    Por qué dos capas: una MAC tiene ~2^24 valores por fabricante, así que un
    SHA-256 solo se revierte por fuerza bruta en segundos. Con el HMAC, quien
    obtenga la base de datos sin el secreto no puede hacerlo, y el mismo router
    da identificadores distintos para usuarios distintos (no se pueden cruzar)."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def network_id(self, owner_id: uuid.UUID, client_fingerprint: str | None) -> str | None:
        if client_fingerprint is None:
            return None
        message = f"{owner_id}:{client_fingerprint}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()
