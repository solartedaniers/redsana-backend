from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityScoreConfig:
    """Rangos del puntaje de seguridad y peso de cada parte. Salen de Settings (SECURITY_SCORE_*) y el frontend los lee
    de GET /api/security-assessments/score-config, así que esta es la única fuente."""

    good_min: int
    warning_min: int
    questionnaire_weight_percent: int
    technical_weight_percent: int
