from typing import Literal

from pydantic import BaseModel


class AnomalyStatusRead(BaseModel):
    status: Literal["calibrating", "active", "unknown_network"]
    samples_collected: int
    samples_required: int
