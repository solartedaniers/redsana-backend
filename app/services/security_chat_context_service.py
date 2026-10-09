import uuid
from collections import Counter
from datetime import tzinfo

from app.domain.device_presence import connected_members, is_device_online, latest_seen_among
from app.domain.security_analyzers import RISKY_ROUTER_PORTS, ROUTER_PORT_SERVICE_NAMES
from app.models.alert import Alert
from app.models.device import Device
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.alert_repository import AlertRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.services.security_assessment_service import SecurityAssessmentResult, SecurityAssessmentService

THIS_DEVICE_ROLE = "this_device"

# Tope de alertas en el contexto para no inflar el prompt; al modelo le bastan las más recientes.
MAX_ALERTS_IN_CONTEXT = 10

_WEAK_ANSWERS = ("no", "unknown")


class SecurityChatContextBuilder:
    """Resume en texto los datos reales del dueño para el system prompt, para que el asistente responda con números reales."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        alert_repository: AlertRepository,
        network_metrics_repository: NetworkMetricsRepository,
        security_assessment_service: SecurityAssessmentService,
        user_timezone: tzinfo,
    ) -> None:
        self._device_repository = device_repository
        self._alert_repository = alert_repository
        self._network_metrics_repository = network_metrics_repository
        self._security_assessment_service = security_assessment_service
        # Escribo las fechas en la hora local del usuario: en UTC una medición nocturna salía como del día siguiente.
        self._user_timezone = user_timezone

    def build(self, owner_id: uuid.UUID) -> str:
        devices = self._device_repository.list_by_owner(owner_id)

        alerts = self._alert_repository.list_all(owner_id)
        unacknowledged = [alert for alert in alerts if not alert.acknowledged]

        snapshot = self._network_metrics_repository.get_latest(owner_id)
        assessment = self._security_assessment_service.get_latest_assessment(owner_id)

        lines = [
            self._devices_line(devices),
            self._alerts_line(unacknowledged),
            self._snapshot_line(snapshot),
            *self._assessment_lines(assessment),
        ]
        return "\n".join(lines)

    def _devices_line(self, devices: list[Device]) -> str:
        # Mismo conteo que la pantalla de Dispositivos; el total histórico no lo doy porque mezcla otras redes.
        latest_seen = latest_seen_among(devices)
        this_device_online = any(
            device.network_role == THIS_DEVICE_ROLE and is_device_online(device, latest_seen) for device in devices
        )
        members = connected_members(devices)
        trust_counts = Counter(device.trust for device in members)
        return (
            f"- Dispositivos conectados en el ultimo escaneo: {len(members) + int(this_device_online)} "
            f"(incluye este equipo, sin contar el router). De los demas: {trust_counts['trusted']} marcados de "
            f"confianza, {trust_counts['blocked']} marcados como inseguros y {trust_counts['unknown']} sin revisar. "
            "RedSana no puede bloquear equipos en el router; el usuario solo los marca."
        )

    def _alerts_line(self, unacknowledged: list[Alert]) -> str:
        if not unacknowledged:
            return "- Alertas activas sin reconocer: ninguna."
        summaries = [
            f"[{alert.severity}/{alert.type}] {alert.message_key} {alert.message_params or ''}".strip()
            for alert in unacknowledged[:MAX_ALERTS_IN_CONTEXT]
        ]
        return f"- Alertas activas sin reconocer ({len(unacknowledged)}): " + "; ".join(summaries)

    def _snapshot_line(self, snapshot: NetworkMetricSnapshot | None) -> str:
        if snapshot is None:
            return "- Ultimo snapshot de red: aun no hay ninguno registrado."
        return (
            "- Ultimo snapshot de red: "
            f"latencia {snapshot.latency_ms:.1f} ms, jitter {snapshot.jitter_ms:.1f} ms, "
            f"perdida de paquetes {snapshot.packet_loss_percent:.1f}%, estado '{snapshot.status}'."
        )

    def _assessment_lines(self, assessment: SecurityAssessmentResult | None) -> list[str]:
        if assessment is None:
            return ["- Evaluacion de seguridad: el usuario aun no ha respondido el cuestionario."]

        score = assessment.security_score
        evidence = assessment.technical_evidence
        if score.is_partial:
            breakdown = (
                f"{score.score}/100, PARCIAL: solo cuestionario ({score.questionnaire_score}/100). "
                "No hay analisis tecnico: nunca se midio la red desde la app de escritorio "
                "(la web no puede medir el cifrado WiFi ni los puertos del router)."
            )
        else:
            measured_on = assessment.technical_measured_at.astimezone(self._user_timezone)
            origin = (
                f"reutilizado de una medicion hecha desde la app de escritorio el {measured_on:%Y-%m-%d}"
                if assessment.technical_evidence_reused
                else f"medido desde la app de escritorio el {measured_on:%Y-%m-%d}"
            )
            breakdown = (
                f"{score.score}/100 = cuestionario {score.questionnaire_score}/100 (pesa 30%) "
                f"+ analisis tecnico {score.technical_score}/100 (pesa 70%, {origin})."
            )

        lines = [f"- Puntaje de seguridad: {breakdown}"]
        if evidence.wifi_encryption_raw is not None:
            lines.append(f"- Cifrado WiFi detectado: {evidence.wifi_encryption_raw}.")
        if evidence.router_open_ports is not None:
            risky = [port for port in evidence.router_open_ports if port in RISKY_ROUTER_PORTS]
            names = ", ".join(f"{port} ({ROUTER_PORT_SERVICE_NAMES[port]})" for port in risky) or "ninguno"
            lines.append(f"- Puertos de riesgo abiertos en el router: {names}.")
        weak = [f"{question}: {answer}" for question, answer in assessment.answers.items() if answer in _WEAK_ANSWERS]
        lines.append(f"- Respuestas debiles del cuestionario: {', '.join(weak) or 'ninguna'}.")
        recommendations = ", ".join(r.id for r in score.recommendations) or "ninguna"
        lines.append(f"- Recomendaciones priorizadas (de mas a menos urgente): {recommendations}.")
        return lines
