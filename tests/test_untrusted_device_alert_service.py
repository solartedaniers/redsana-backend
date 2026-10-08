import uuid
from datetime import datetime, timedelta, timezone

from app.models.device import Device
from app.services.untrusted_device_alert_service import UNTRUSTED_DEVICE_ALERT_TYPE, UntrustedDeviceAlertService
from tests.test_alert_service import FakeAlertRepository

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _device(trust: str, role: str = "other", seen: datetime = NOW, ip: str = "10.0.0.5") -> Device:
    return Device(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="", mac_address=uuid.uuid4().hex[:12],
                  ip_address=ip, trust=trust, network_role=role, first_seen=seen, last_seen=seen)


def _alerts(repository: FakeAlertRepository, owner_id: uuid.UUID):
    return [a for a in repository.list_all(owner_id) if a.type == UNTRUSTED_DEVICE_ALERT_TYPE]


def test_an_unsafe_device_seen_in_the_scan_raises_one_alert_with_its_ip() -> None:
    repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    unsafe = _device("blocked", ip="10.0.0.66")

    UntrustedDeviceAlertService(repository).alert_for_scan(owner_id, [unsafe, _device("trusted"), _device("unknown")], NOW)

    alerts = _alerts(repository, owner_id)
    assert len(alerts) == 1
    assert alerts[0].message_params == {"device_id": str(unsafe.id), "ip": "10.0.0.66"}
    assert alerts[0].message_key == "user.alertsCenter.messages.untrustedDeviceOnline"


def test_rescanning_within_24_hours_does_not_repeat_the_alert() -> None:
    repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    unsafe = _device("blocked")
    service = UntrustedDeviceAlertService(repository)

    service.alert_for_scan(owner_id, [unsafe], NOW)
    service.alert_for_scan(owner_id, [unsafe], NOW + timedelta(hours=1))

    assert len(_alerts(repository, owner_id)) == 1


def test_unsafe_devices_not_in_the_latest_scan_or_the_router_do_not_alert() -> None:
    repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    gone = _device("blocked", seen=NOW - timedelta(days=2))
    router = _device("blocked", role="gateway")
    present = _device("unknown")

    UntrustedDeviceAlertService(repository).alert_for_scan(owner_id, [gone, router, present], NOW)

    assert _alerts(repository, owner_id) == []
