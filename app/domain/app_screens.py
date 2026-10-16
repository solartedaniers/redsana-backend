"""Pantallas reales del usuario en la app, para que el asistente no invente menús ni rutas.
 Cada texto es el del es.json del frontend en esa clave; una prueba los compara para que no se desincronicen."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenText:
    i18n_key: str
    text: str


@dataclass(frozen=True)
class AppScreen:
    title: ScreenText
    sections: tuple[ScreenText, ...] = ()


USER_APP_SCREENS: tuple[AppScreen, ...] = (
    AppScreen(
        ScreenText("user.dashboard.title", "Panel principal"),
        (
            ScreenText("user.dashboard.latency", "Latencia"),
            ScreenText("user.dashboard.jitter", "Jitter"),
            ScreenText("user.dashboard.packetLoss", "Pérdida de paquetes"),
            ScreenText("user.dashboard.historyTitle", "Historial de latencia"),
        ),
    ),
    AppScreen(ScreenText("user.securityAssistant.title", "Asistente de seguridad")),
    AppScreen(ScreenText("user.alertsCenter.title", "Centro de alertas")),
    AppScreen(ScreenText("user.devicesMap.title", "Dispositivos conectados")),
    AppScreen(ScreenText("user.familyMode.title", "Modo familiar")),
    AppScreen(ScreenText("user.download.title", "Descargar")),
    AppScreen(ScreenText("auth.profile.title", "Mi perfil")),
)


def all_screen_texts() -> list[ScreenText]:
    return [text for screen in USER_APP_SCREENS for text in (screen.title, *screen.sections)]
