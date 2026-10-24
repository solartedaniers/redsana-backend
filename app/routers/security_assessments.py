from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authorization import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.schemas.security_assessment import (
    SecurityAssessmentCreate,
    SecurityAssessmentRead,
    SecurityRecommendationRead,
    SecurityScoreConfigRead,
)
from app.services.network_security_score_service import default_network_security_score_service
from app.services.security_assessment_service import SecurityAssessmentResult, SecurityAssessmentService

router = APIRouter(prefix="/api/security-assessments", tags=["security-assessments"])


def _to_read(result: SecurityAssessmentResult) -> SecurityAssessmentRead:
    security_score = result.security_score
    return SecurityAssessmentRead(
        id=result.id,
        score=security_score.score,
        questionnaire_score=security_score.questionnaire_score,
        technical_score=security_score.technical_score,
        is_partial=security_score.is_partial,
        technical_measured_at=result.technical_measured_at,
        technical_evidence_reused=result.technical_evidence_reused,
        recommendations=[
            SecurityRecommendationRead(
                id=r.id, title_key=r.title_key, description_key=r.description_key, priority=r.priority
            )
            for r in security_score.recommendations
        ],
        submitted_at=result.submitted_at,
    )


@router.get("/score-config", response_model=SecurityScoreConfigRead)
def get_score_config(_user: User = Depends(get_current_user)) -> SecurityScoreConfigRead:
    """Solo lectura: los mismos rangos y pesos con que el backend calcula y describe el puntaje."""
    config = get_settings().security_score_config
    return SecurityScoreConfigRead(
        good_min=config.good_min,
        warning_min=config.warning_min,
        questionnaire_weight_percent=config.questionnaire_weight_percent,
        technical_weight_percent=config.technical_weight_percent,
    )


@router.get("/latest", response_model=SecurityAssessmentRead | None)
def get_latest_assessment(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecurityAssessmentRead | None:
    """None es que el usuario nunca respondió: el frontend muestra el formulario vacío, no un error."""
    service = SecurityAssessmentService(
        SqlAlchemySecurityAssessmentRepository(db), default_network_security_score_service()
    )
    result = service.get_latest_assessment(user.id)
    return _to_read(result) if result is not None else None


@router.post("", response_model=SecurityAssessmentRead, status_code=201)
def submit_assessment(
    payload: SecurityAssessmentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecurityAssessmentRead:
    """Cada usuario solo registra su propia evaluación; nadie contesta el cuestionario del router de otro."""
    service = SecurityAssessmentService(
        SqlAlchemySecurityAssessmentRepository(db), default_network_security_score_service()
    )
    result = service.submit_assessment(user.id, payload)
    return _to_read(result)
