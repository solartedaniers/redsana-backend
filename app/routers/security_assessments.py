from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authorization import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.schemas.security_assessment import SecurityAssessmentCreate, SecurityAssessmentRead, SecurityRecommendationRead
from app.services.security_assessment_service import SecurityAssessmentResult, SecurityAssessmentService

router = APIRouter(prefix="/api/security-assessments", tags=["security-assessments"])


def _to_read(result: SecurityAssessmentResult) -> SecurityAssessmentRead:
    return SecurityAssessmentRead(
        score=result.score,
        recommendations=[
            SecurityRecommendationRead(id=r.id, title_key=r.title_key, description_key=r.description_key, priority=r.priority)
            for r in result.recommendations
        ],
        submitted_at=result.submitted_at,
    )


@router.get("/latest", response_model=SecurityAssessmentRead | None)
def get_latest_assessment(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecurityAssessmentRead | None:
    """None significa "el usuario nunca ha respondido el cuestionario": el
    frontend debe mostrar el formulario vacío en ese caso, no un error."""
    service = SecurityAssessmentService(SqlAlchemySecurityAssessmentRepository(db))
    result = service.get_latest_assessment(user.id)
    return _to_read(result) if result is not None else None


@router.post("", response_model=SecurityAssessmentRead, status_code=201)
def submit_assessment(
    payload: SecurityAssessmentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecurityAssessmentRead:
    """Cada usuario solo puede registrar su propia evaluación (sin override de
    admin: nadie más contesta el cuestionario del router de otra persona)."""
    service = SecurityAssessmentService(SqlAlchemySecurityAssessmentRepository(db))
    result = service.submit_assessment(user.id, payload)
    return _to_read(result)
