from typing import Literal, get_args

# native = ping ICMP de la app de escritorio (Rust); web = fetch cronometrado
# desde el navegador. Miden la misma red pero con escalas de latencia distintas
# (HTTP suma tiempo de servidor), por eso el detector de anomalias nunca mezcla
# fuentes en un mismo historial.
MeasurementSource = Literal["native", "web"]
MEASUREMENT_SOURCE_VALUES: tuple[str, ...] = get_args(MeasurementSource)

# Los instaladores de escritorio anteriores a esta columna no envian `source`:
# todo lo que llega sin ella (y todo el historial previo) es ping nativo.
DEFAULT_MEASUREMENT_SOURCE: MeasurementSource = "native"
