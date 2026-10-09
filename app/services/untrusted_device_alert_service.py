import uuid
from datetime import datetime, timedelta, timezone

from app.domain.alert_messages import alert_message_key
from app.domain.device_presence import connected_members
from app.models.device import Device
from app.repositories.alert_repository import AlertRepository

UNTRUSTED_DEVICE_ALERT_TYPE = "untrusted_device"
UNTRUSTED_DEVICE_ALERT_SEVERITY = "warning"
UNTRUSTED_DEVICE_MESSAGE_KEY = alert_message_key("untrustedDeviceOnline")
# "blocked" es el valor interno de "Inseguro"; lo conservo para no romper el .exe ya instalado.
UNTRUSTED_DEVICE_TRUST = "blocked"
# Una alerta por equipo cada 24 h: se escanea en cada visita y sin esto habría una por escaneo.
UNTRUSTED_DEVICE_ALERT_COOLDOWN = timedelta(hours=24)


class UntrustedDeviceAlertService:
    """Avisa cuando un equipo marcado como inseguro aparece conectado; RedSana no puede bloquear nada en el router."""

    def __init__(self, alert_repository: AlertRepository) -> None:
        self._alert_repository = alert_repository

    def alert_for_scan(self, owner_id: uuid.UUID, devices: list[Device], now: datetime | None = None) -> None:
        unsafe = [device for device in connected_members(devices) if device.trust == UNTRUSTED_DEVICE_TRUST]
        if not unsafe:
            return

        now = now or datetime.now(timezone.utc)
        recent = self._alert_repository.list_new_since(owner_id, now - UNTRUSTED_DEVICE_ALERT_COOLDOWN)
        already_alerted = {
            (alert.message_params or {}).get("device_id")
            for alert in recent
            if alert.type == UNTRUSTED_DEVICE_ALERT_TYPE
        }
        for device in unsafe:
            if str(device.id) in already_alerted:
                continue
            self._alert_repository.create(
                owner_id=owner_id,
                type_=UNTRUSTED_DEVICE_ALERT_TYPE,
                severity=UNTRUSTED_DEVICE_ALERT_SEVERITY,
                # Sin la MAC: con la IP basta para que el usuario lo ubique.
                message_params={"device_id": str(device.id), "ip": device.ip_address},
                message_key=UNTRUSTED_DEVICE_MESSAGE_KEY,
                created_at=None,
            )
