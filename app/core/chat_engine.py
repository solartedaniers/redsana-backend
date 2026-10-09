from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatTurn:
    role: ChatRole
    content: str


class ChatEngineError(Exception):
    """El motor no pudo responder (red, cuota o respuesta inválida)."""


class ChatEngine(ABC):
    """Interfaz del modelo conversacional: cambiar Groq por otro proveedor es escribir una clase nueva."""

    @abstractmethod
    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        """turns: la conversación en orden, terminando en el mensaje a responder."""
