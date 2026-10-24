import json
import uuid
from collections import Counter
from datetime import datetime, timezone, tzinfo
from pathlib import Path

from app.core.config import get_settings
from app.domain.app_screens import USER_APP_SCREENS
from app.domain.device_presence import connected_members, is_device_online, latest_seen_among
from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE, MeasurementSource
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

# Textos del contexto. La regla final existe porque la IA inventaba umbrales ("> 200 ms") y menús
# ("Dashboard → Estado de la Red"); le doy los reales y se lo prohíbo.
_TEXT = json.loads(
    (Path(__file__).parent.parent / "resources" / "security_chat_context.es.json").read_text(encoding="utf-8")
)
_MEASUREMENT_ORIGINS: dict[MeasurementSource, str] = _TEXT["measurement_origins"]


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
            self._thresholds_line(snapshot.source if snapshot is not None else DEFAULT_MEASUREMENT_SOURCE),
            self._screens_line(),
            *self._assessment_lines(assessment),
            _TEXT["only_context_facts_rule"],
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
        return _TEXT["devices"].format(
            connected=len(members) + int(this_device_online),
            trusted=trust_counts["trusted"],
            blocked=trust_counts["blocked"],
            unknown=trust_counts["unknown"],
        )

    def _alerts_line(self, unacknowledged: list[Alert]) -> str:
        if not unacknowledged:
            return _TEXT["alerts_none"]
        summaries = [
            f"[{alert.severity}/{alert.type}] {alert.message_key} {alert.message_params or ''}".strip()
            for alert in unacknowledged[:MAX_ALERTS_IN_CONTEXT]
        ]
        return _TEXT["alerts"].format(count=len(unacknowledged), summaries="; ".join(summaries))

    def _snapshot_line(self, snapshot: NetworkMetricSnapshot | None) -> str:
        if snapshot is None:
            return _TEXT["snapshot_none"]
        # SQLite devuelve la fecha sin zona; la guardo siempre en UTC.
        recorded_at = (
            snapshot.recorded_at if snapshot.recorded_at.tzinfo else snapshot.recorded_at.replace(tzinfo=timezone.utc)
        )
        minutes_ago = max(0, int((datetime.now(timezone.utc) - recorded_at).total_seconds() // 60))
        local_time = recorded_at.astimezone(self._user_timezone)
        return _TEXT["snapshot"].format(
            latency_ms=snapshot.latency_ms,
            jitter_ms=snapshot.jitter_ms,
            packet_loss_percent=snapshot.packet_loss_percent,
            status=snapshot.status,
            local_time=local_time,
            minutes_ago=minutes_ago,
            origin=_MEASUREMENT_ORIGINS[snapshot.source],
        )

    def _thresholds_line(self, source: MeasurementSource) -> str:
        thresholds = get_settings().network_status_thresholds_for(source)
        # :g (en el recurso) escribe 80 y no 80.0, como el texto que ya conocía el asistente.
        return _TEXT["thresholds"].format(
            latency_warning_ms=thresholds.latency_warning_ms,
            packet_loss_warning_percent=thresholds.packet_loss_warning_percent,
            latency_critical_ms=thresholds.latency_critical_ms,
            packet_loss_critical_percent=thresholds.packet_loss_critical_percent,
        )

    def _screens_line(self) -> str:
        screens = "; ".join(
            f"{screen.title.text} ({', '.join(section.text for section in screen.sections)})"
            if screen.sections
            else screen.title.text
            for screen in USER_APP_SCREENS
        )
        return _TEXT["screens"].format(screens=screens)

    def _assessment_lines(self, assessment: SecurityAssessmentResult | None) -> list[str]:
        if assessment is None:
            return [_TEXT["assessment_none"]]

        score = assessment.security_score
        evidence = assessment.technical_evidence
        if score.is_partial:
            breakdown = _TEXT["score_partial"].format(score=score.score, questionnaire_score=score.questionnaire_score)
        else:
            measured_on = assessment.technical_measured_at.astimezone(self._user_timezone)
            origin_key = "origin_reused" if assessment.technical_evidence_reused else "origin_measured"
            weights = get_settings().security_score_config
            breakdown = _TEXT["score_full"].format(
                score=score.score,
                questionnaire_score=score.questionnaire_score,
                questionnaire_weight=weights.questionnaire_weight_percent,
                technical_score=score.technical_score,
                technical_weight=weights.technical_weight_percent,
                origin=_TEXT[origin_key].format(measured_on=measured_on),
            )

        lines = [_TEXT["score"].format(breakdown=breakdown)]
        if evidence.wifi_encryption_raw is not None:
            lines.append(_TEXT["wifi"].format(encryption=evidence.wifi_encryption_raw))
        if evidence.router_open_ports is not None:
            risky = [port for port in evidence.router_open_ports if port in RISKY_ROUTER_PORTS]
            names = ", ".join(f"{port} ({ROUTER_PORT_SERVICE_NAMES[port]})" for port in risky)
            lines.append(_TEXT["risky_ports"].format(ports=names or _TEXT["risky_ports_none"]))
        weak = [f"{question}: {answer}" for question, answer in assessment.answers.items() if answer in _WEAK_ANSWERS]
        lines.append(_TEXT["weak_answers"].format(answers=", ".join(weak) or _TEXT["none"]))
        recommendations = ", ".join(r.id for r in score.recommendations) or _TEXT["none"]
        lines.append(_TEXT["recommendations"].format(recommendations=recommendations))
        return lines
