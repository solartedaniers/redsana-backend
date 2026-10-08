"""Cada clave de alerta que guarda el backend debe existir en los diccionarios
del frontend: si no, el Centro de alertas muestra la clave cruda (pasó con
"alertsCenter.messages.briefOutage")."""
import json
from pathlib import Path

import pytest

from app.domain.network_anomaly import _MESSAGE_KEYS
from app.services.outage_detection_service import OUTAGE_MESSAGE_KEY
from app.services.untrusted_device_alert_service import UNTRUSTED_DEVICE_MESSAGE_KEY

I18N_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "assets" / "i18n"
BACKEND_ALERT_KEYS = [OUTAGE_MESSAGE_KEY, UNTRUSTED_DEVICE_MESSAGE_KEY, *_MESSAGE_KEYS.values()]


def _resolve(dictionary: dict, key: str):
    current = dictionary
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


@pytest.mark.parametrize("language", ["es", "en"])
def test_every_backend_alert_key_has_a_frontend_text(language: str) -> None:
    dictionary = json.loads((I18N_DIR / f"{language}.json").read_text(encoding="utf-8"))
    missing = [key for key in BACKEND_ALERT_KEYS if not isinstance(_resolve(dictionary, key), str)]
    assert missing == []
