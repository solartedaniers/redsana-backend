from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.security_assessment import SecurityRecommendation

MAX_ANALYZER_SCORE = 100


@dataclass(frozen=True)
class TechnicalEvidence:
    """Lo que la app de escritorio midió de la red real. None en un campo =
    no se pudo medir (p. ej. desde la web), que no es lo mismo que "medido y mal"."""

    wifi_encryption_raw: str | None
    router_open_ports: list[int] | None


@dataclass(frozen=True)
class AnalyzerResult:
    score: int  # 0..MAX_ANALYZER_SCORE
    weight: int  # peso relativo dentro del análisis técnico
    recommendations: list[SecurityRecommendation]


class TechnicalSecurityAnalyzer(ABC):
    """Strategy: cada analizador evalúa un solo aspecto técnico de la red. Un
    analizador nuevo solo implementa esto y se registra en
    default_technical_analyzers(); los existentes no se tocan."""

    @abstractmethod
    def analyze(self, evidence: TechnicalEvidence) -> AnalyzerResult | None:
        """None si la evidencia que necesita no está disponible: el analizador
        no puntúa (ni a favor ni en contra) lo que no pudo medir."""


# Puntaje por tipo de cifrado según el campo "Autenticación" de netsh (el orden
# importa: "WPA2"/"WPA3" deben evaluarse antes que el prefijo genérico "WPA").
_WIFI_ENCRYPTION_SCORES: tuple[tuple[str, int], ...] = (
    ("WPA3", 100),
    ("WPA2", 85),
    ("WPA", 35),
    ("WEP", 10),
    ("SHARED", 10),
    ("CLAVE COMPARTIDA", 10),
    ("OPEN", 0),
    ("ABIERTA", 0),
)
# Por debajo de esto (WPA o peor) se recomienda cambiar el cifrado.
_MIN_ACCEPTABLE_WIFI_ENCRYPTION_SCORE = 85

_WIFI_ENCRYPTION_RECOMMENDATION = SecurityRecommendation(
    "enable-wifi-encryption",
    "user.securityAssistant.recommendations.enableWifiEncryption.title",
    "user.securityAssistant.recommendations.enableWifiEncryption.description",
    3,
)


class WifiEncryptionAnalyzer(TechnicalSecurityAnalyzer):
    WEIGHT = 50

    def analyze(self, evidence: TechnicalEvidence) -> AnalyzerResult | None:
        if not evidence.wifi_encryption_raw:
            return None
        normalized = evidence.wifi_encryption_raw.upper()
        score = next((score for prefix, score in _WIFI_ENCRYPTION_SCORES if normalized.startswith(prefix)), None)
        if score is None:
            # Valor de netsh que no reconocemos: no se arriesga un puntaje inventado.
            return None
        recommendations = [] if score >= _MIN_ACCEPTABLE_WIFI_ENCRYPTION_SCORE else [_WIFI_ENCRYPTION_RECOMMENDATION]
        return AnalyzerResult(score=score, weight=self.WEIGHT, recommendations=recommendations)


def _port_recommendation(key: str, priority: int) -> SecurityRecommendation:
    prefix = f"user.securityAssistant.recommendations.{key}"
    return SecurityRecommendation(f"router-port-{key}", f"{prefix}.title", f"{prefix}.description", priority)


_TELNET = _port_recommendation("closeTelnet", 1)
_FTP = _port_recommendation("closeFtp", 2)
_FILE_SHARING = _port_recommendation("closeFileSharing", 2)
_TR069 = _port_recommendation("closeRemoteProvisioning", 3)
_SSH = _port_recommendation("closeSsh", 4)

# Puerto -> (puntos que resta, recomendación). Espejo intencional de
# PROBED_PORTS en frontend/src-tauri/src/router_ports.rs (que solo los prueba).
RISKY_ROUTER_PORTS: dict[int, tuple[int, SecurityRecommendation]] = {
    23: (60, _TELNET),  # Telnet: administración sin cifrar, vector clásico de botnets
    21: (35, _FTP),  # FTP: credenciales y archivos en texto plano
    445: (30, _FILE_SHARING),  # SMB expuesto en el router
    139: (20, _FILE_SHARING),  # NetBIOS (SMB antiguo)
    7547: (25, _TR069),  # TR-069: administración remota del proveedor, muy atacada
    22: (10, _SSH),  # SSH: cifrado, pero es una puerta de administración abierta
}


class RouterOpenPortsAnalyzer(TechnicalSecurityAnalyzer):
    WEIGHT = 50

    def analyze(self, evidence: TechnicalEvidence) -> AnalyzerResult | None:
        if evidence.router_open_ports is None:
            return None
        risky = [RISKY_ROUTER_PORTS[port] for port in sorted(set(evidence.router_open_ports)) if port in RISKY_ROUTER_PORTS]
        penalty = sum(points for points, _ in risky)
        # dict.fromkeys: 139 y 445 comparten recomendación, se muestra una sola vez.
        recommendations = list(dict.fromkeys(recommendation for _, recommendation in risky))
        return AnalyzerResult(
            score=max(0, MAX_ANALYZER_SCORE - penalty), weight=self.WEIGHT, recommendations=recommendations
        )


def default_technical_analyzers() -> list[TechnicalSecurityAnalyzer]:
    return [WifiEncryptionAnalyzer(), RouterOpenPortsAnalyzer()]
