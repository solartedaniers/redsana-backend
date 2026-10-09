from typing import Literal, get_args

# Papel del dispositivo según el último escaneo; this_device se agrega aparte porque no sale en su propia tabla ARP.
DeviceRole = Literal["this_device", "gateway", "other"]
DEVICE_ROLE_VALUES: tuple[str, ...] = get_args(DeviceRole)

# Los escritorios con la versión anterior no envían el papel.
DEFAULT_DEVICE_ROLE: DeviceRole = "other"
