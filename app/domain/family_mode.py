# Copia a propósito de family-dns.ts y de la guía del Modo familiar: es el contexto con el que guía el asistente.
FAMILY_DNS_PRIMARY = "1.1.1.3"
FAMILY_DNS_SECONDARY = "1.0.0.3"

FAMILY_MODE_GUIDE_STEPS: tuple[str, ...] = (
    "Abrir el panel del router en el navegador (suele ser 192.168.0.1 o 192.168.1.1; viene en la etiqueta del router).",
    "Entrar con el usuario y la contraseña de administración del router (suelen estar en esa misma etiqueta).",
    'Buscar la sección "Internet", "WAN", "DHCP" o "LAN" y dentro la opción "DNS"; si está en automático, pasarla a manual.',
    f"Escribir {FAMILY_DNS_PRIMARY} como DNS primario y {FAMILY_DNS_SECONDARY} como DNS secundario.",
    "Guardar los cambios y reiniciar el router si lo pide.",
)
