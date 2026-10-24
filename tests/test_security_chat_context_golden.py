"""El texto completo del contexto del asistente, escenario por escenario: moverlo a un recurso no puede cambiar nada."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.security_analyzers import TechnicalEvidence, default_technical_analyzers
from app.models.alert import Alert
from app.models.device import Device
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.services import security_chat_context_service
from app.services.network_security_score_service import NetworkSecurityScoreService
from app.services.security_assessment_service import SecurityAssessmentResult
from app.services.security_chat_context_service import SecurityChatContextBuilder

NOW = datetime(2026, 3, 14, 2, 30, tzinfo=timezone.utc)
BOGOTA = timezone(timedelta(hours=-5))
OWNER = uuid.uuid4()


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class _Fixed:
    def __init__(self, value) -> None:
        self._value = value

    def list_by_owner(self, owner_id):
        return self._value

    list_all = list_by_owner
    get_latest = list_by_owner
    get_latest_assessment = list_by_owner


def _device(trust: str, role: str) -> Device:
    return Device(
        id=uuid.uuid4(),
        owner_id=OWNER,
        name="",
        mac_address=uuid.uuid4().hex[:12],
        ip_address="10.0.0.1",
        trust=trust,
        network_role=role,
        first_seen=NOW,
        last_seen=NOW,
    )


def _alert(severity: str, kind: str, key: str, params: dict | None, acknowledged: bool = False) -> Alert:
    return Alert(severity=severity, type=kind, message_key=key, message_params=params, acknowledged=acknowledged)


def _snapshot(source: str) -> NetworkMetricSnapshot:
    return NetworkMetricSnapshot(
        latency_ms=263.14,
        jitter_ms=16.05,
        packet_loss_percent=2.0,
        status="critical",
        source=source,
        recorded_at=NOW - timedelta(minutes=7, seconds=40),
    )


def _assessment(answers: dict[str, str], evidence: TechnicalEvidence, reused: bool) -> SecurityAssessmentResult:
    measured = evidence.wifi_encryption_raw is not None or evidence.router_open_ports is not None
    return SecurityAssessmentResult(
        id=uuid.uuid4(),
        answers=answers,
        technical_evidence=evidence,
        security_score=NetworkSecurityScoreService(default_technical_analyzers()).evaluate(answers, evidence),
        submitted_at=NOW,
        technical_measured_at=NOW if measured else None,
        technical_evidence_reused=reused,
    )


ALL_YES = {"default-password": "yes", "firmware-updated": "yes", "guest-network": "yes", "remote-management-off": "yes"}
WEAK = {"default-password": "no", "firmware-updated": "unknown", "guest-network": "yes", "remote-management-off": "no"}


def _build(devices, alerts, snapshot, assessment) -> str:
    builder = SecurityChatContextBuilder(_Fixed(devices), _Fixed(alerts), _Fixed(snapshot), _Fixed(assessment), BOGOTA)
    return builder.build(OWNER)


SCENARIOS = {
    "vacio": lambda: _build([], [], None, None),
    "completo": lambda: _build(
        [
            _device("unknown", "gateway"),
            _device("unknown", "this_device"),
            _device("trusted", "other"),
            _device("blocked", "other"),
            _device("unknown", "other"),
        ],
        [
            _alert("critical", "outage", "alerts.outage", {"minutes": 3}),
            _alert("info", "prediction", "alerts.prediction", None, acknowledged=True),
            _alert("warning", "untrusted_device", "alerts.untrusted", None),
        ],
        _snapshot("web"),
        _assessment(WEAK, TechnicalEvidence(wifi_encryption_raw="WPA2", router_open_ports=[23, 80, 445]), False),
    ),
    "parcial_nativo": lambda: _build(
        [_device("trusted", "other")],
        [_alert("warning", "outage", f"alerts.k{i}", None) for i in range(12)],
        _snapshot("native"),
        _assessment(WEAK, TechnicalEvidence(wifi_encryption_raw=None, router_open_ports=None), False),
    ),
    "reutilizado_sin_riesgos": lambda: _build(
        [],
        [],
        None,
        _assessment(ALL_YES, TechnicalEvidence(wifi_encryption_raw="WPA3", router_open_ports=[80]), True),
    ),
}

# Generado con el código de main antes de mover el texto; no se edita a mano. Única excepción: "completo" mide desde la
# web y desde el lote B recibe los umbrales de la web (400 / 800 ms).
EXPECTED: dict[str, str] = {
    "completo": (
        "- Dispositivos conectados en el ultimo escaneo: 4 (incluye este equipo, sin contar el router). De los demas: 1 marcados de confianza, 1 marcados como inseguros y 1 sin revisar. RedSana no puede bloquear equipos en el router; el usuario solo los marca."
        "\n- Alertas activas sin reconocer (2): [critical/outage] alerts.outage {'minutes': 3}; [warning/untrusted_device] alerts.untrusted"
        "\n- Ultimo snapshot de red: latencia 263.1 ms, jitter 16.1 ms, perdida de paquetes 2.0%, estado 'critical'. Medido el 2026-03-13 21:22 (hora local, hace 7 min) desde la web (latencia al servidor: peticiones HTTPS al servidor de RedSana, incluye el viaje hasta el servidor; no es un ping a la red local)."
        "\n- Umbrales reales del estado de la red (fijos, no dependen del historial): alerta desde 400 ms de latencia o 1% de perdida; critica desde 800 ms o 5% de perdida. El jitter no cambia el estado."
        "\n- Pantallas reales de la app: Panel principal (Latencia, Jitter, Pérdida de paquetes, Historial de latencia); Asistente de seguridad; Centro de alertas; Dispositivos conectados; Modo familiar; Descargar; Mi perfil."
        "\n- Puntaje de seguridad: 39/100 = cuestionario 19/100 (pesa 30%) + analisis tecnico 48/100 (pesa 70%, medido desde la app de escritorio el 2026-03-13)."
        "\n- Cifrado WiFi detectado: WPA2."
        "\n- Puertos de riesgo abiertos en el router: 23 (Telnet), 445 (SMB (archivos compartidos))."
        "\n- Respuestas debiles del cuestionario: default-password: no, firmware-updated: unknown, remote-management-off: no."
        "\n- Recomendaciones priorizadas (de mas a menos urgente): change-default-password, router-port-closeTelnet, check-firmware, router-port-closeFileSharing, disable-remote-management."
        "\n- Regla: para umbrales, fechas, origen de la medicion y nombres de pantallas o secciones usa solo los de este contexto; no inventes otros valores, menus ni rutas."
    ),
    "parcial_nativo": (
        "- Dispositivos conectados en el ultimo escaneo: 1 (incluye este equipo, sin contar el router). De los demas: 1 marcados de confianza, 0 marcados como inseguros y 0 sin revisar. RedSana no puede bloquear equipos en el router; el usuario solo los marca."
        "\n- Alertas activas sin reconocer (12): [warning/outage] alerts.k0; [warning/outage] alerts.k1; [warning/outage] alerts.k2; [warning/outage] alerts.k3; [warning/outage] alerts.k4; [warning/outage] alerts.k5; [warning/outage] alerts.k6; [warning/outage] alerts.k7; [warning/outage] alerts.k8; [warning/outage] alerts.k9"
        "\n- Ultimo snapshot de red: latencia 263.1 ms, jitter 16.1 ms, perdida de paquetes 2.0%, estado 'critical'. Medido el 2026-03-13 21:22 (hora local, hace 7 min) desde la app de escritorio (ping ICMP a internet)."
        "\n- Umbrales reales del estado de la red (fijos, no dependen del historial): alerta desde 80 ms de latencia o 1% de perdida; critica desde 150 ms o 5% de perdida. El jitter no cambia el estado."
        "\n- Pantallas reales de la app: Panel principal (Latencia, Jitter, Pérdida de paquetes, Historial de latencia); Asistente de seguridad; Centro de alertas; Dispositivos conectados; Modo familiar; Descargar; Mi perfil."
        "\n- Puntaje de seguridad: 19/100, PARCIAL: solo cuestionario (19/100). No hay analisis tecnico: nunca se midio la red desde la app de escritorio (la web no puede medir el cifrado WiFi ni los puertos del router)."
        "\n- Respuestas debiles del cuestionario: default-password: no, firmware-updated: unknown, remote-management-off: no."
        "\n- Recomendaciones priorizadas (de mas a menos urgente): change-default-password, check-firmware, disable-remote-management."
        "\n- Regla: para umbrales, fechas, origen de la medicion y nombres de pantallas o secciones usa solo los de este contexto; no inventes otros valores, menus ni rutas."
    ),
    "reutilizado_sin_riesgos": (
        "- Dispositivos conectados en el ultimo escaneo: 0 (incluye este equipo, sin contar el router). De los demas: 0 marcados de confianza, 0 marcados como inseguros y 0 sin revisar. RedSana no puede bloquear equipos en el router; el usuario solo los marca."
        "\n- Alertas activas sin reconocer: ninguna."
        "\n- Ultimo snapshot de red: aun no hay ninguno registrado."
        "\n- Umbrales reales del estado de la red (fijos, no dependen del historial): alerta desde 80 ms de latencia o 1% de perdida; critica desde 150 ms o 5% de perdida. El jitter no cambia el estado."
        "\n- Pantallas reales de la app: Panel principal (Latencia, Jitter, Pérdida de paquetes, Historial de latencia); Asistente de seguridad; Centro de alertas; Dispositivos conectados; Modo familiar; Descargar; Mi perfil."
        "\n- Puntaje de seguridad: 100/100 = cuestionario 100/100 (pesa 30%) + analisis tecnico 100/100 (pesa 70%, reutilizado de una medicion hecha desde la app de escritorio el 2026-03-13)."
        "\n- Cifrado WiFi detectado: WPA3."
        "\n- Puertos de riesgo abiertos en el router: ninguno."
        "\n- Respuestas debiles del cuestionario: ninguna."
        "\n- Recomendaciones priorizadas (de mas a menos urgente): ninguna."
        "\n- Regla: para umbrales, fechas, origen de la medicion y nombres de pantallas o secciones usa solo los de este contexto; no inventes otros valores, menus ni rutas."
    ),
    "vacio": (
        "- Dispositivos conectados en el ultimo escaneo: 0 (incluye este equipo, sin contar el router). De los demas: 0 marcados de confianza, 0 marcados como inseguros y 0 sin revisar. RedSana no puede bloquear equipos en el router; el usuario solo los marca."
        "\n- Alertas activas sin reconocer: ninguna."
        "\n- Ultimo snapshot de red: aun no hay ninguno registrado."
        "\n- Umbrales reales del estado de la red (fijos, no dependen del historial): alerta desde 80 ms de latencia o 1% de perdida; critica desde 150 ms o 5% de perdida. El jitter no cambia el estado."
        "\n- Pantallas reales de la app: Panel principal (Latencia, Jitter, Pérdida de paquetes, Historial de latencia); Asistente de seguridad; Centro de alertas; Dispositivos conectados; Modo familiar; Descargar; Mi perfil."
        "\n- Evaluacion de seguridad: el usuario aun no ha respondido el cuestionario."
        "\n- Regla: para umbrales, fechas, origen de la medicion y nombres de pantallas o secciones usa solo los de este contexto; no inventes otros valores, menus ni rutas."
    ),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_context_text_is_exactly_the_same(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security_chat_context_service, "datetime", _FrozenDatetime)

    assert SCENARIOS[name]() == EXPECTED[name]
