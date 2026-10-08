# Las alertas guardan la clave i18n del frontend y el frontend la traduce tal
# cual: tiene que ser la ruta completa del diccionario. Sin el "user." las
# alertas se veían como "alertsCenter.messages.briefOutage" en vez del texto.
ALERT_MESSAGE_KEY_PREFIX = "user.alertsCenter.messages."


def alert_message_key(name: str) -> str:
    return f"{ALERT_MESSAGE_KEY_PREFIX}{name}"
