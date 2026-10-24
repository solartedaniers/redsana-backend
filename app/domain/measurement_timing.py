from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def as_utc(moment: datetime) -> datetime:
    """Una hora sin zona se toma como UTC (SQLite y algunos clientes la mandan así)."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@dataclass(frozen=True)
class MeasurementTimingPolicy:
    """Qué hora de medición se acepta y cuándo una medición llegó tarde (reenviada desde la cola del cliente)."""

    max_age: timedelta
    max_future: timedelta
    late_after: timedelta

    def rejection_reason(self, recorded_at: datetime, now: datetime) -> str | None:
        if recorded_at - now > self.max_future:
            return "recorded_at is in the future"
        if now - recorded_at > self.max_age:
            return "recorded_at is older than the accepted maximum age"
        return None

    def is_late(self, recorded_at: datetime, now: datetime) -> bool:
        return now - recorded_at > self.late_after
