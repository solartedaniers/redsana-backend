from datetime import datetime

from pydantic import BaseModel

from app.domain.security_assessment import AnswerValue


class SecurityAssessmentCreate(BaseModel):
    """Respuestas manuales del cuestionario + evidencia técnica medida por la app
    de escritorio (None en cada campo si no se pudo medir, p.ej. desde la web)."""

    answers: dict[str, AnswerValue]
    wifi_encryption_raw: str | None = None
    router_open_ports: list[int] | None = None


class SecurityRecommendationRead(BaseModel):
    id: str
    title_key: str
    description_key: str
    priority: int


class SecurityAssessmentRead(BaseModel):
    score: int
    questionnaire_score: int
    technical_score: int | None
    is_partial: bool
    recommendations: list[SecurityRecommendationRead]
    submitted_at: datetime
