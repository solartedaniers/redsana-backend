"""Cada clave de alerta del backend debe existir en el frontend, o el Centro de alertas muestra la clave cruda.
Los diccionarios viven en el repo del frontend: FRONTEND_I18N_DIR (entorno o .env) dice dónde están."""

import json
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.domain.network_anomaly_policy import ANOMALY_MESSAGE_KEYS
from app.services.outage_detection_service import OUTAGE_MESSAGE_KEY
from app.services.untrusted_device_alert_service import UNTRUSTED_DEVICE_MESSAGE_KEY

BACKEND_DIR = Path(__file__).resolve().parents[1]
I18N_DIR_VARIABLE = "FRONTEND_I18N_DIR"
BACKEND_ALERT_KEYS = [OUTAGE_MESSAGE_KEY, UNTRUSTED_DEVICE_MESSAGE_KEY, *ANOMALY_MESSAGE_KEYS.values()]


def _resolve(dictionary: dict, key: str):
    current = dictionary
    for segment in key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _i18n_dir() -> Path | None:
    # Ruta relativa a la carpeta del backend, para que funcione igual desde cualquier directorio.
    raw = os.environ.get(I18N_DIR_VARIABLE) or dotenv_values(BACKEND_DIR / ".env").get(I18N_DIR_VARIABLE)
    return BACKEND_DIR / raw if raw else None


@pytest.mark.parametrize("language", ["es", "en"])
def test_every_backend_alert_key_has_a_frontend_text(language: str) -> None:
    i18n_dir = _i18n_dir()
    if i18n_dir is None:
        pytest.skip(
            f"{I18N_DIR_VARIABLE} no está definida: clona el repo del frontend y apúntala a su public/assets/i18n"
        )
    dictionary = json.loads((i18n_dir / f"{language}.json").read_text(encoding="utf-8"))
    missing = [key for key in BACKEND_ALERT_KEYS if not isinstance(_resolve(dictionary, key), str)]
    assert missing == []
