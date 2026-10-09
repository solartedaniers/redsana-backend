from dataclasses import dataclass

from app.domain.measurement_source import MeasurementSource


@dataclass(frozen=True)
class BaselineScope:
    """Qué mediciones son el comportamiento normal: misma fuente y misma red (None solo coincide con None)."""

    source: MeasurementSource
    network_id: str | None


def baseline_scope(source: MeasurementSource, network_id: str | None) -> BaselineScope | None:
    """None es red desconocida: no hay historial con qué comparar. En escritorio cada red se aprende por separado;
     en la web no se puede identificar la red, así que uso todo el historial web del usuario."""
    if source == "native" and network_id is None:
        return None
    return BaselineScope(source=source, network_id=network_id)
