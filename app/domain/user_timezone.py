from datetime import timedelta, timezone

# Límite real de los husos horarios (UTC-12 a UTC+14), en minutos.
MAX_UTC_OFFSET_MINUTES = 14 * 60


def timezone_from_browser_offset(utc_offset_minutes: int) -> timezone:
    """getTimezoneOffset() da los minutos que hay que SUMAR para llegar a UTC (Colombia = 300); invierto el signo."""
    return timezone(-timedelta(minutes=utc_offset_minutes))
