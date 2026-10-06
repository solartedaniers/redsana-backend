import ipaddress
import re

from app.domain.family_mode import FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY

# La interfaz del chat muestra texto plano: el modelo a veces responde con
# Markdown aunque se le pida que no, así que se limpia antes de guardar.
_EMPHASIS = re.compile(r"(\*\*|__|`)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_FAMILY_DNS = {FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY}
# Redes locales (RFC 1918): donde vive el panel del router. No se usa
# is_private porque Python también cuenta 0.0.0.0/8 como privada, y "0.0.0.3"
# es justamente el error de copia que hay que atrapar.
_LOCAL_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def to_plain_text(reply: str) -> str:
    return _HEADING.sub("", _EMPHASIS.sub("", reply)).strip()


def mentions_unexpected_dns(reply: str) -> bool:
    """True si la respuesta nombra una IP que no es de red local ni uno de los
    DNS de familia. Las locales (192.168.x.x, la del router) son esperables. Existe
    porque el modelo llegó a escribir "0.0.0.3" en vez de "1.0.0.3": un error de
    copia así deja al usuario sin internet, y no se puede confiar solo en el prompt."""
    for candidate in _IPV4.findall(reply):
        try:
            address = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue
        is_local = any(address in network for network in _LOCAL_NETWORKS)
        if not is_local and candidate not in _FAMILY_DNS:
            return True
    return False
