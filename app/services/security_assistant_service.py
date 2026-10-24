import uuid

from redsana_ai import BriefingLanguage, ChatTurn, SecurityBriefing, SecurityChat, family_mode_topic_context

from app.domain.chat_topic import ChatTopic
from app.domain.family_mode import FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY, FAMILY_MODE_GUIDE_STEPS
from app.services.security_chat_context_service import SecurityChatContextBuilder

_TOPIC_CONTEXTS: dict[ChatTopic, str] = {
    "family_mode": family_mode_topic_context(FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY, FAMILY_MODE_GUIDE_STEPS),
}


class SecurityAssistantService:
    """Traduce dueño y tema del backend a lo que pide el asistente de redsana_ai (datos reales ya armados)."""

    def __init__(
        self, chat: SecurityChat, briefing: SecurityBriefing, context_builder: SecurityChatContextBuilder
    ) -> None:
        self._chat = chat
        self._briefing = briefing
        self._context_builder = context_builder

    def ask(self, owner_id: uuid.UUID, history: list[ChatTurn], user_message: str, topic: ChatTopic | None) -> str:
        topic_context = _TOPIC_CONTEXTS.get(topic) if topic else None
        return self._chat.ask(self._context_builder.build(owner_id), history, user_message, topic_context)

    def write_briefing(self, owner_id: uuid.UUID, language: BriefingLanguage) -> str:
        return self._briefing.write(self._context_builder.build(owner_id), language)
