from dataclasses import dataclass

from app.domain.measurement_source import MeasurementSource


@dataclass(frozen=True)
class BaselineScope:
    """Qué mediciones forman el "comportamiento normal" contra el que se compara
    una medición nueva: misma fuente y misma red (None coincide solo con None)."""

    source: MeasurementSource
    network_id: str | None


def baseline_scope(source: MeasurementSource, network_id: str | None) -> BaselineScope | None:
    """None = red desconocida: no hay historial válido contra el que comparar.

    - Escritorio: cada red se aprende por separado (network_id = hash de la MAC
      del router). Una medición nativa sin red (historial previo a esta función,
      escritorio sin actualizar o router no resuelto) no se asigna a ninguna red
      adivinando: no calibra ni se evalúa.
    - Web: el navegador no puede identificar la red local, así que conserva el
      comportamiento previo (todo el historial web del usuario, sin red)."""
    if source == "native" and network_id is None:
        return None
    return BaselineScope(source=source, network_id=network_id)
