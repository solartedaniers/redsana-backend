from datetime import datetime

from pydantic import BaseModel

from app.domain.security_assessment import AnswerValue


class SecurityAssessmentCreate(BaseModel):
    """Respuestas manuales del cuestionario + cifrado WiFi auto-detectado por
    Tauri (None si no se pudo detectar, p.ej. corriendo fuera de Tauri)."""

    answers: dict[str, AnswerValue]
    wifi_encryption_raw: str | None = None


class SecurityRecommendationRead(BaseModel):
    id: str
    title_key: str
    description_key: str
    priority: int


class SecurityAssessmentRead(BaseModel):
    score: int
    recommendations: list[SecurityRecommendationRead]
    submitted_at: datetime
