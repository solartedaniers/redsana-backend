import pytest

from app.domain.router_password_guard import contains_password_disclosure


@pytest.mark.parametrize(
    "message",
    [
        "mi contraseña es Casa2024",
        "La clave del wifi es admin",
        "la contraseña de mi router es: Tp-Link#55",
        "password: admin123",
        "my router password is hunter22",
        "pwd=qwerty",
        "la contrasena es 'secreto'",
    ],
)
def test_detects_when_the_user_writes_a_password(message: str) -> None:
    assert contains_password_disclosure(message)


@pytest.mark.parametrize(
    "message",
    [
        "¿Cómo cambio la contraseña de mi router?",
        "¿Mi contraseña es segura?",
        "la clave es muy corta?",
        "Is my password strong enough?",
        "Olvidé la contraseña del wifi, ¿qué hago?",
        "¿Dónde veo la clave del router?",
        "Tengo Telnet abierto, ¿cómo lo cierro?",
        "el bypass: activado en el firewall",
    ],
)
def test_ignores_questions_about_passwords(message: str) -> None:
    assert not contains_password_disclosure(message)
