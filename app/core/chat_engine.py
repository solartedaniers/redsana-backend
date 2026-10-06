from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatTurn:
    role: ChatRole
    content: str


class ChatEngineError(Exception):
    """El motor no pudo responder (red, cuota, respuesta inválida)."""


class ChatEngine(ABC):
    """Strategy del modelo conversacional: el resto del dominio solo conoce
    esta interfaz, así cambiar Groq por otro proveedor es una clase nueva."""

    @abstractmethod
    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        """turns: conversación en orden cronológico, terminando en el mensaje a responder."""
