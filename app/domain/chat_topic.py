from typing import Literal, get_args

# Tema con el que nace una conversación: define el contexto extra que recibe el
# asistente. None = conversación libre (la que el usuario abre escribiendo).
ChatTopic = Literal["assessment_briefing", "family_mode"]
CHAT_TOPIC_VALUES: tuple[str, ...] = get_args(ChatTopic)

# El usuario solo puede abrir a mano conversaciones de estos temas; el resumen
# de una evaluación lo crea el backend (uno por evaluación).
UserStartableChatTopic = Literal["family_mode"]
