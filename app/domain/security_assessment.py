from dataclasses import dataclass
from typing import Literal

AnswerValue = Literal["yes", "no", "unknown"]

# Pesos de las 4 preguntas manuales + el cifrado WiFi auto-detectado, suman 100.
# Espejo intencional de security-score.calculator.ts (frontend); no hay código
# compartido entre frontend y backend.
QUESTION_WEIGHTS: dict[str, int] = {
    "default-password": 25,
    "firmware-updated": 20,
    "guest-network": 15,
    "remote-management-off": 20,
}
WIFI_ENCRYPTION_WEIGHT = 20

# Prefijos de netsh que cuentan como cifrado fuerte (mismo criterio que la
# pregunta original "¿Tienes WPA3, o al menos WPA2?").
_STRONG_WIFI_ENCRYPTION_PREFIXES = ("WPA3", "WPA2")


@dataclass(frozen=True)
class SecurityRecommendation:
    id: str
    title_key: str
    description_key: str
    priority: int


# Una entrada "no" (corrígelo) y otra "unknown" (ve a revisarlo) por pregunta:
# el texto debe sonar distinto según si el usuario confirmó el problema o
# simplemente no lo sabe.
_RECOMMENDATIONS: dict[str, dict[Literal["no", "unknown"], SecurityRecommendation]] = {
    "default-password": {
        "no": SecurityRecommendation(
            "change-default-password",
            "user.securityAssistant.recommendations.changeDefaultPassword.title",
            "user.securityAssistant.recommendations.changeDefaultPassword.description",
            1,
        ),
        "unknown": SecurityRecommendation(
            "check-default-password",
            "user.securityAssistant.recommendations.checkDefaultPassword.title",
            "user.securityAssistant.recommendations.checkDefaultPassword.description",
            1,
        ),
    },
    "firmware-updated": {
        "no": SecurityRecommendation(
            "update-firmware",
            "user.securityAssistant.recommendations.updateFirmware.title",
            "user.securityAssistant.recommendations.updateFirmware.description",
            2,
        ),
        "unknown": SecurityRecommendation(
            "check-firmware",
            "user.securityAssistant.recommendations.checkFirmware.title",
            "user.securityAssistant.recommendations.checkFirmware.description",
            2,
        ),
    },
    "guest-network": {
        "no": SecurityRecommendation(
            "enable-guest-network",
            "user.securityAssistant.recommendations.enableGuestNetwork.title",
            "user.securityAssistant.recommendations.enableGuestNetwork.description",
            4,
        ),
        "unknown": SecurityRecommendation(
            "check-guest-network",
            "user.securityAssistant.recommendations.checkGuestNetwork.title",
            "user.securityAssistant.recommendations.checkGuestNetwork.description",
            4,
        ),
    },
    "remote-management-off": {
        "no": SecurityRecommendation(
            "disable-remote-management",
            "user.securityAssistant.recommendations.disableRemoteManagement.title",
            "user.securityAssistant.recommendations.disableRemoteManagement.description",
            5,
        ),
        "unknown": SecurityRecommendation(
            "check-remote-management",
            "user.securityAssistant.recommendations.checkRemoteManagement.title",
            "user.securityAssistant.recommendations.checkRemoteManagement.description",
            5,
        ),
    },
}

_WIFI_ENCRYPTION_RECOMMENDATION = SecurityRecommendation(
    "enable-wifi-encryption",
    "user.securityAssistant.recommendations.enableWifiEncryption.title",
    "user.securityAssistant.recommendations.enableWifiEncryption.description",
    3,
)


def is_strong_wifi_encryption(wifi_encryption_raw: str | None) -> bool:
    if not wifi_encryption_raw:
        return False
    return wifi_encryption_raw.upper().startswith(_STRONG_WIFI_ENCRYPTION_PREFIXES)


def compute_security_assessment(
    answers: dict[str, AnswerValue], wifi_encryption_raw: str | None
) -> tuple[int, list[SecurityRecommendation]]:
    """Preguntas sin responder cuentan como "unknown" (0 puntos), igual que "no"."""
    total_weight = sum(QUESTION_WEIGHTS.values()) + WIFI_ENCRYPTION_WEIGHT
    earned_weight = sum(
        weight for question_id, weight in QUESTION_WEIGHTS.items() if answers.get(question_id) == "yes"
    )
    wifi_is_strong = is_strong_wifi_encryption(wifi_encryption_raw)
    if wifi_is_strong:
        earned_weight += WIFI_ENCRYPTION_WEIGHT
    score = round((earned_weight / total_weight) * 100)

    recommendations = [
        _RECOMMENDATIONS[question_id][answers.get(question_id, "unknown")]
        for question_id in QUESTION_WEIGHTS
        if answers.get(question_id, "unknown") in ("no", "unknown")
    ]
    if not wifi_is_strong:
        recommendations.append(_WIFI_ENCRYPTION_RECOMMENDATION)

    recommendations.sort(key=lambda r: r.priority)
    return score, recommendations
