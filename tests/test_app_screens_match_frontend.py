"""Las pantallas que le doy a la IA deben llamarse igual que en el frontend, o volvería a mandar a menús que no existen."""

import json

import pytest

from app.domain.app_screens import all_screen_texts
from tests.test_alert_message_keys_exist_in_frontend import I18N_DIR_VARIABLE, _i18n_dir, _resolve


def test_every_screen_text_matches_the_frontend_spanish_text() -> None:
    i18n_dir = _i18n_dir()
    if i18n_dir is None:
        pytest.skip(
            f"{I18N_DIR_VARIABLE} no está definida: clona el repo del frontend y apúntala a su public/assets/i18n"
        )
    dictionary = json.loads((i18n_dir / "es.json").read_text(encoding="utf-8"))
    mismatched = [
        (screen.i18n_key, screen.text, _resolve(dictionary, screen.i18n_key))
        for screen in all_screen_texts()
        if _resolve(dictionary, screen.i18n_key) != screen.text
    ]
    assert mismatched == []
