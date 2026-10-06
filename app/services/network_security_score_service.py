from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.security_analyzers import TechnicalEvidence, TechnicalSecurityAnalyzer, default_technical_analyzers
from app.domain.security_assessment import AnswerValue, SecurityRecommendation, compute_questionnaire_score

QUESTIONNAIRE_WEIGHT_PERCENT = 30
TECHNICAL_WEIGHT_PERCENT = 70


@dataclass(frozen=True)
class NetworkSecurityScore:
    score: int
    questionnaire_score: int
    # None = no hubo evidencia técnica (p. ej. evaluado desde la web): el
    # puntaje es solo del cuestionario y se informa como parcial.
    technical_score: int | None
    recommendations: list[SecurityRecommendation]

    @property
    def is_partial(self) -> bool:
        return self.technical_score is None


class NetworkSecurityScoreService:
    """Combina cuestionario (30%) y análisis técnico (70%). No sabe qué mide
    cada analizador: solo promedia, por peso, los que pudieron evaluar algo."""

    def __init__(self, analyzers: Sequence[TechnicalSecurityAnalyzer]) -> None:
        self._analyzers = analyzers

    def evaluate(self, answers: dict[str, AnswerValue], evidence: TechnicalEvidence) -> NetworkSecurityScore:
        questionnaire_score, recommendations = compute_questionnaire_score(answers)
        results = [result for analyzer in self._analyzers if (result := analyzer.analyze(evidence)) is not None]

        technical_score: int | None = None
        score = questionnaire_score
        if results:
            total_weight = sum(result.weight for result in results)
            technical_score = round(sum(result.score * result.weight for result in results) / total_weight)
            score = round(
                (questionnaire_score * QUESTIONNAIRE_WEIGHT_PERCENT + technical_score * TECHNICAL_WEIGHT_PERCENT) / 100
            )
            recommendations = recommendations + [r for result in results for r in result.recommendations]

        return NetworkSecurityScore(
            score=score,
            questionnaire_score=questionnaire_score,
            technical_score=technical_score,
            recommendations=sorted(recommendations, key=lambda r: r.priority),
        )


def default_network_security_score_service() -> NetworkSecurityScoreService:
    return NetworkSecurityScoreService(default_technical_analyzers())
