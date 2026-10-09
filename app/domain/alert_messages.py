# Guardo la ruta completa de la clave i18n: sin el "user." el frontend mostraba la clave cruda.
ALERT_MESSAGE_KEY_PREFIX = "user.alertsCenter.messages."


def alert_message_key(name: str) -> str:
    return f"{ALERT_MESSAGE_KEY_PREFIX}{name}"
