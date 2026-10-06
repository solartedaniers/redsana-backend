from typing import Literal, get_args

# Papel del dispositivo en la red, según el último escaneo que lo vio. Lo marca
# la app de escritorio: el router es la red misma y "this_device" es el equipo
# que escanea (no aparece en su propia tabla ARP, se agrega aparte).
DeviceRole = Literal["this_device", "gateway", "other"]
DEVICE_ROLE_VALUES: tuple[str, ...] = get_args(DeviceRole)

# Escritorios con la versión anterior no envían el papel.
DEFAULT_DEVICE_ROLE: DeviceRole = "other"
