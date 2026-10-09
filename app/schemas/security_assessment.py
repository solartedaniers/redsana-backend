import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.security_assessment import AnswerValue


class SecurityAssessmentCreate(BaseModel):
    """Respuestas del cuestionario más la evidencia técnica del escritorio (None en lo que no se pudo medir)."""

    answers: dict[str, AnswerValue]
    wifi_encryption_raw: str | None = None
    router_open_ports: list[int] | None = None


class SecurityRecommendationRead(BaseModel):
    id: str
    title_key: str
    description_key: str
    priority: int


class SecurityAssessmentRead(BaseModel):
    id: uuid.UUID
    score: int
    questionnaire_score: int
    technical_score: int | None
    is_partial: bool
    # Fecha de la medición técnica usada y si se reutilizó de una evaluación anterior.
    technical_measured_at: datetime | None
    technical_evidence_reused: bool
    recommendations: list[SecurityRecommendationRead]
    submitted_at: datetime
