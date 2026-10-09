from typing import Literal, get_args

# native es ping ICMP del escritorio y web es fetch cronometrado; las escalas no son comparables,
# así que el detector nunca mezcla fuentes en un historial.
MeasurementSource = Literal["native", "web"]
MEASUREMENT_SOURCE_VALUES: tuple[str, ...] = get_args(MeasurementSource)

# Los instaladores anteriores a esta columna no envían `source`: todo lo que llega sin ella es ping nativo.
DEFAULT_MEASUREMENT_SOURCE: MeasurementSource = "native"
