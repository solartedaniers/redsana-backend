"""Sin base: la presencia sale de last_seen relativo al grupo, nunca del tiempo transcurrido."""

import uuid
from datetime import datetime, timedelta, timezone

from app.domain.device_presence import MANUAL_SCAN_PRESENCE_TOLERANCE, is_device_online, latest_seen_among
from app.models.device import Device


def _device(last_seen: datetime) -> Device:
    return Device(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="x",
        mac_address="AA",
        ip_address="1.1.1.1",
        trust="unknown",
        first_seen=last_seen,
        last_seen=last_seen,
    )


def test_device_touched_by_the_latest_scan_is_online() -> None:
    now = datetime.now(timezone.utc)
    just_synced = _device(now)
    devices = [just_synced]

    assert is_device_online(just_synced, latest_seen_among(devices)) is True


def test_device_missing_from_the_latest_scan_is_offline() -> None:
    now = datetime.now(timezone.utc)
    stale = _device(now - timedelta(days=3))
    fresh = _device(now)
    devices = [stale, fresh]
    latest_seen = latest_seen_among(devices)

    assert is_device_online(stale, latest_seen) is False
    assert is_device_online(fresh, latest_seen) is True


def test_no_scan_ever_run_means_offline() -> None:
    device = _device(datetime.now(timezone.utc))

    assert is_device_online(device, latest_seen_among([])) is False


def test_manual_scan_drops_a_device_seen_seconds_before() -> None:
    now = datetime.now(timezone.utc)
    seconds_ago = _device(now - timedelta(seconds=5))
    latest_seen = latest_seen_among([seconds_ago, _device(now)])

    # El escaneo automático lo tolera; el manual exige que haya respondido en este escaneo.
    assert is_device_online(seconds_ago, latest_seen) is True
    assert is_device_online(seconds_ago, latest_seen, MANUAL_SCAN_PRESENCE_TOLERANCE) is False


if __name__ == "__main__":
    test_device_touched_by_the_latest_scan_is_online()
    test_device_missing_from_the_latest_scan_is_offline()
    test_no_scan_ever_run_means_offline()
    test_manual_scan_drops_a_device_seen_seconds_before()
    print("OK")
