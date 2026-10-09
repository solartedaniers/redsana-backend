import uuid

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository


def _has_technical_evidence():
    # La columna JSON guarda None como 'null' de JSON y no como NULL de SQL: comparo ambos o toda evaluación web parecería tener puertos.
    return or_(
        SecurityAssessment.wifi_encryption_raw.is_not(None),
        func.coalesce(cast(SecurityAssessment.router_open_ports, String), "null") != "null",
    )


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

    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        return self._latest_by_owners(owner_ids)

    def get_latest_with_evidence(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        stmt = (
            select(SecurityAssessment)
            .where(SecurityAssessment.owner_id == owner_id, _has_technical_evidence())
            .order_by(SecurityAssessment.submitted_at.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def get_latest_with_evidence_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        return self._latest_by_owners(owner_ids, _has_technical_evidence())

    def _latest_by_owners(self, owner_ids: list[uuid.UUID], *conditions) -> dict[uuid.UUID, SecurityAssessment]:
        if not owner_ids:
            return {}
        rank = (
            func.row_number()
            .over(partition_by=SecurityAssessment.owner_id, order_by=SecurityAssessment.submitted_at.desc())
            .label("rank")
        )
        ranked = (
            select(SecurityAssessment, rank).where(SecurityAssessment.owner_id.in_(owner_ids), *conditions).subquery()
        )
        assessment = aliased(SecurityAssessment, ranked)
        stmt = select(assessment).where(ranked.c.rank == 1)
        return {row.owner_id: row for row in self._db.scalars(stmt).all()}

    def create(
        self,
        owner_id: uuid.UUID,
        answers: dict[str, str],
        wifi_encryption_raw: str | None,
        router_open_ports: list[int] | None,
    ) -> SecurityAssessment:
        assessment = SecurityAssessment(
            owner_id=owner_id,
            answers=answers,
            wifi_encryption_raw=wifi_encryption_raw,
            router_open_ports=router_open_ports,
        )
        self._db.add(assessment)
        self._db.commit()
        self._db.refresh(assessment)
        return assessment
