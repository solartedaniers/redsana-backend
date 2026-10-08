from datetime import datetime, timedelta

from app.models.device import Device

# El router es la red misma y este equipo es el que escanea: ninguno de los dos
# es un "dispositivo conectado" sobre el que el usuario decida confiar o no.
NON_MEMBER_ROLES = frozenset({"gateway", "this_device"})

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


def connected_members(devices: list[Device]) -> list[Device]:
    """Los dispositivos del último escaneo que no son el router ni este equipo:
    lo que la pantalla de Dispositivos cuenta como "conectados" a la red."""
    latest_seen = latest_seen_among(devices)
    return [
        device
        for device in devices
        if is_device_online(device, latest_seen) and device.network_role not in NON_MEMBER_ROLES
    ]
