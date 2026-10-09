import ipaddress
import re

from app.domain.family_mode import FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY

# El chat muestra texto plano y el modelo a veces responde en Markdown aunque se le pida que no: lo limpio antes de guardar.
_EMPHASIS = re.compile(r"(\*\*|__|`)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_FAMILY_DNS = {FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY}
# Redes locales RFC 1918. No uso is_private porque Python cuenta 0.0.0.0/8 como privada, y "0.0.0.3" es justo el error a atrapar.
_LOCAL_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def to_plain_text(reply: str) -> str:
    return _HEADING.sub("", _EMPHASIS.sub("", reply)).strip()


def mentions_unexpected_dns(reply: str) -> bool:
    """True si la respuesta nombra una IP que no es local ni de los DNS de familia. Existe porque el modelo llegó
     a escribir "0.0.0.3" en vez de "1.0.0.3", y un error así deja al usuario sin internet."""
    for candidate in _IPV4.findall(reply):
        try:
            address = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue
        is_local = any(address in network for network in _LOCAL_NETWORKS)
        if not is_local and candidate not in _FAMILY_DNS:
            return True
    return False
