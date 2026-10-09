"""Ponderación 30 % cuestionario y 70 % técnico, y extensibilidad por analizadores."""
from app.domain.security_analyzers import (
    AnalyzerResult,
    RouterOpenPortsAnalyzer,
    TechnicalEvidence,
    TechnicalSecurityAnalyzer,
    WifiEncryptionAnalyzer,
)
from app.services.network_security_score_service import NetworkSecurityScoreService, default_network_security_score_service

ALL_YES = {"default-password": "yes", "firmware-updated": "yes", "guest-network": "yes", "remote-management-off": "yes"}
ALL_NO = {question: "no" for question in ALL_YES}
NO_EVIDENCE = TechnicalEvidence(wifi_encryption_raw=None, router_open_ports=None)


def test_technical_analysis_weighs_70_percent() -> None:
    # Cuestionario perfecto pero WiFi abierta y Telnet y FTP abiertos: manda la red real.
    evidence = TechnicalEvidence(wifi_encryption_raw="Abierta", router_open_ports=[21, 23])

    result = default_network_security_score_service().evaluate(ALL_YES, evidence)

    assert result.questionnaire_score == 100
    assert result.technical_score == 2  # (0 * 50 + 5 * 50) / 100 = 2.5 -> 2
    assert result.score == 31  # 100 * 30% + 2 * 70% = 31.4


def test_bad_answers_cannot_hide_a_good_network_either() -> None:
    evidence = TechnicalEvidence(wifi_encryption_raw="WPA3-Personal", router_open_ports=[])

    result = default_network_security_score_service().evaluate(ALL_NO, evidence)

    assert (result.questionnaire_score, result.technical_score, result.score) == (0, 100, 70)


def test_missing_evidence_is_not_scored_as_bad() -> None:
    result = default_network_security_score_service().evaluate(ALL_YES, NO_EVIDENCE)

    assert result.is_partial
    assert result.score == 100


def test_only_measured_analyzers_count_in_the_technical_score() -> None:
    # Los puertos sin medir no pesan; el técnico es solo el cifrado WPA2 (85).
    evidence = TechnicalEvidence(wifi_encryption_raw="WPA2-Personal", router_open_ports=None)

    assert default_network_security_score_service().evaluate(ALL_YES, evidence).technical_score == 85


def test_a_new_analyzer_plugs_in_without_touching_the_others() -> None:
    class AlwaysZeroAnalyzer(TechnicalSecurityAnalyzer):
        def analyze(self, evidence: TechnicalEvidence) -> AnalyzerResult | None:
            return AnalyzerResult(score=0, weight=100, recommendations=[])

    service = NetworkSecurityScoreService([WifiEncryptionAnalyzer(), RouterOpenPortsAnalyzer(), AlwaysZeroAnalyzer()])
    evidence = TechnicalEvidence(wifi_encryption_raw="WPA3", router_open_ports=[])

    # (100 * 50 + 100 * 50 + 0 * 100) / 200 = 50
    assert service.evaluate(ALL_YES, evidence).technical_score == 50


def test_wifi_analyzer_grades_each_encryption_and_ignores_unknown_values() -> None:
    analyzer = WifiEncryptionAnalyzer()

    def grade(raw: str) -> int | None:
        result = analyzer.analyze(TechnicalEvidence(raw, None))
        return result.score if result else None

    raws = ("WPA3-Personal", "WPA2-Enterprise", "WPA-Personal", "WEP", "Open", "Abierta")
    assert [grade(raw) for raw in raws] == [100, 85, 35, 10, 0, 0]
    assert grade("Algo-Nuevo") is None


def test_ports_analyzer_penalizes_risky_ports_and_dedupes_file_sharing_advice() -> None:
    result = RouterOpenPortsAnalyzer().analyze(TechnicalEvidence(None, [139, 445, 80, 23]))

    assert result is not None
    assert result.score == 0  # 100 - (20 + 30 + 60), con piso en 0; el 80 no es de riesgo
    assert [r.id for r in result.recommendations] == ["router-port-closeTelnet", "router-port-closeFileSharing"]
