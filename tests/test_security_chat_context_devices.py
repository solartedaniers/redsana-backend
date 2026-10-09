"""La IA recibe el mismo conteo que ve el usuario en Dispositivos, no el total histórico."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.device import Device
from app.services.security_chat_context_service import SecurityChatContextBuilder


def _device(trust: str, role: str, seen: datetime) -> Device:
    return Device(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="", mac_address=uuid.uuid4().hex[:12],
                  ip_address="10.0.0.1", trust=trust, network_role=role, first_seen=seen, last_seen=seen)


def test_devices_line_counts_like_the_devices_screen_and_breaks_down_marks() -> None:
    now = datetime.now(timezone.utc)
    devices = [
        _device("unknown", "gateway", now),
        _device("unknown", "this_device", now),
        _device("trusted", "other", now),
        _device("blocked", "other", now),
        _device("unknown", "other", now),
        *[_device("unknown", "other", now - timedelta(days=2)) for _ in range(40)],  # historial
    ]
    builder = SecurityChatContextBuilder(None, None, None, None, timezone.utc)

    line = builder._devices_line(devices)

    assert "ultimo escaneo: 4 " in line  # 3 equipos más este PC, sin el router ni el historial
    assert "1 marcados de confianza, 1 marcados como inseguros y 1 sin revisar" in line
