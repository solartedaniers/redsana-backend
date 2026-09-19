from datetime import datetime, timedelta

from app.models.device import Device

# Los escaneos son manuales (el usuario dispara el botón), no periódicos: que haya
# pasado tiempo desde el último escaneo no significa que el dispositivo se haya
# desconectado. La señal real de presencia es si quedó fuera de la última tanda
# de sincronización, no cuánto tiempo absoluto pasó.
DEVICE_PRESENCE_TOLERANCE = timedelta(seconds=30)


def latest_seen_among(devices: list[Device]) -> datetime | None:
    return max((device.last_seen for device in devices), default=None)


def is_device_online(device: Device, latest_seen: datetime | None) -> bool:
    """True si a este dispositivo lo tocó la sincronización más reciente del
    owner (su last_seen está a menos de DEVICE_PRESENCE_TOLERANCE del más
    reciente del grupo); False si quedó fuera del último escaneo real."""
    if latest_seen is None:
        return False
    return (latest_seen - device.last_seen) <= DEVICE_PRESENCE_TOLERANCE
