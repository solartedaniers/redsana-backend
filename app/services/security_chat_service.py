import uuid

from app.core.chat_engine import ChatEngine, ChatTurn
from app.domain.assistant_reply import to_plain_text
from app.domain.chat_topic import ChatTopic
from app.services.security_chat_prompt_builder import SecurityChatPromptBuilder

# Mensajes previos que van al modelo: suficientes para seguir el hilo sin inflar el prompt.
CHAT_HISTORY_LIMIT = 12


class SecurityChatService:
    """Responde un mensaje con el modelo, dándole las reglas, los datos reales y el historial reciente."""

    def __init__(self, engine: ChatEngine, prompt_builder: SecurityChatPromptBuilder) -> None:
        self._engine = engine
        self._prompt_builder = prompt_builder

    def ask(self, owner_id: uuid.UUID, history: list[ChatTurn], user_message: str, topic: ChatTopic | None) -> str:
        system_prompt = self._prompt_builder.build(owner_id, topic)
        turns = [*history[-CHAT_HISTORY_LIMIT:], ChatTurn("user", user_message)]
        return to_plain_text(self._engine.complete(system_prompt, turns))
