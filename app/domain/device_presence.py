from datetime import datetime, timedelta

from app.models.device import Device

# El router es la red misma y este equipo es quien escanea: ninguno es un dispositivo sobre el que decidir confianza.
NON_MEMBER_ROLES = frozenset({"gateway", "this_device"})

# Los escaneos son manuales, así que el tiempo transcurrido no dice nada: lo que cuenta es haber quedado
# fuera de la última sincronización.
DEVICE_PRESENCE_TOLERANCE = timedelta(seconds=30)


def latest_seen_among(devices: list[Device]) -> datetime | None:
    return max((device.last_seen for device in devices), default=None)


def is_device_online(device: Device, latest_seen: datetime | None) -> bool:
    """True si la última sincronización del dueño tocó este dispositivo; False si quedó fuera del último escaneo."""
    if latest_seen is None:
        return False
    return (latest_seen - device.last_seen) <= DEVICE_PRESENCE_TOLERANCE


def connected_members(devices: list[Device]) -> list[Device]:
    """Lo que la pantalla de Dispositivos cuenta como conectado: el último escaneo sin el router ni este equipo."""
    latest_seen = latest_seen_among(devices)
    return [
        device
        for device in devices
        if is_device_online(device, latest_seen) and device.network_role not in NON_MEMBER_ROLES
    ]
