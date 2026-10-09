from typing import Literal, get_args

# Tema con el que nace la conversación; None es una conversación libre que abre el usuario escribiendo.
ChatTopic = Literal["assessment_briefing", "family_mode"]
CHAT_TOPIC_VALUES: tuple[str, ...] = get_args(ChatTopic)

# El usuario solo abre a mano estos temas; el resumen de una evaluación lo crea el backend.
UserStartableChatTopic = Literal["family_mode"]
