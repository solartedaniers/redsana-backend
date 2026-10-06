from datetime import timedelta, timezone

# Límite real de los husos horarios (UTC-12 a UTC+14), en minutos.
MAX_UTC_OFFSET_MINUTES = 14 * 60


def timezone_from_browser_offset(utc_offset_minutes: int) -> timezone:
    """El navegador reporta Date.getTimezoneOffset(): minutos que hay que SUMAR
    a la hora local para llegar a UTC (Colombia = 300). Se invierte el signo
    para obtener el huso real (UTC-5), sin depender de una base de zonas horarias."""
    return timezone(-timedelta(minutes=utc_offset_minutes))
