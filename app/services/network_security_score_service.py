from collections.abc import Sequence
from dataclasses import dataclass

from app.core.config import get_settings
from app.domain.security_analyzers import TechnicalEvidence, TechnicalSecurityAnalyzer, default_technical_analyzers
from app.domain.security_assessment import AnswerValue, SecurityRecommendation, compute_questionnaire_score
from app.domain.security_score_config import SecurityScoreConfig


@dataclass(frozen=True)
class NetworkSecurityScore:
    score: int
    questionnaire_score: int
    # None es que no hubo evidencia técnica: el puntaje sale solo del cuestionario y es parcial.
    technical_score: int | None
    recommendations: list[SecurityRecommendation]

    @property
    def is_partial(self) -> bool:
        return self.technical_score is None


class NetworkSecurityScoreService:
    """Combina cuestionario y análisis técnico según sus pesos, promediando por peso los analizadores que midieron."""

    def __init__(
        self, analyzers: Sequence[TechnicalSecurityAnalyzer], config: SecurityScoreConfig | None = None
    ) -> None:
        self._analyzers = analyzers
        self._config = config or get_settings().security_score_config

    def evaluate(self, answers: dict[str, AnswerValue], evidence: TechnicalEvidence) -> NetworkSecurityScore:
        questionnaire_score, recommendations = compute_questionnaire_score(answers)
        results = [result for analyzer in self._analyzers if (result := analyzer.analyze(evidence)) is not None]

        technical_score: int | None = None
        score = questionnaire_score
        if results:
            total_weight = sum(result.weight for result in results)
            technical_score = round(sum(result.score * result.weight for result in results) / total_weight)
            score = round(
                (
                    questionnaire_score * self._config.questionnaire_weight_percent
                    + technical_score * self._config.technical_weight_percent
                )
                / 100
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
