import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository


class SqlAlchemySecurityAssessmentRepository(SecurityAssessmentRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        stmt = (
            select(SecurityAssessment)
            .where(SecurityAssessment.owner_id == owner_id)
            .order_by(SecurityAssessment.submitted_at.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def create(
        self, owner_id: uuid.UUID, answers: dict[str, str], wifi_encryption_raw: str | None
    ) -> SecurityAssessment:
        assessment = SecurityAssessment(owner_id=owner_id, answers=answers, wifi_encryption_raw=wifi_encryption_raw)
        self._db.add(assessment)
        self._db.commit()
        self._db.refresh(assessment)
        return assessment
