import uuid
from typing import Literal

from app.core.chat_engine import ChatEngine, ChatTurn
from app.domain.assistant_reply import to_plain_text
from app.services.security_chat_prompt_builder import SecurityChatPromptBuilder

BriefingLanguage = Literal["es", "en"]

_LANGUAGE_NAMES: dict[BriefingLanguage, str] = {"es": "espanol", "en": "ingles"}

# Instrucción interna (el usuario no la ve y no se guarda) para el primer mensaje tras una evaluación.
_BRIEFING_REQUEST = """\
El usuario acaba de enviar su evaluacion de seguridad. Escribe TU el primer mensaje \
de la conversacion, en {language}, en lenguaje sencillo y sin jerga:
1. Su puntaje y el desglose (cuestionario 30% y analisis tecnico 70%).
2. De donde sale el analisis tecnico: si se midio desde la app de escritorio, dilo con \
su fecha; si fue reutilizado de una medicion anterior, dilo con su fecha; si NO hay \
analisis tecnico, explica con honestidad que el puntaje es solo del cuestionario y que \
el cifrado WiFi y los puertos del router solo se pueden medir desde la app de escritorio.
3. Que encontro, empezando por lo mas urgente (puertos de riesgo abiertos como Telnet, \
cifrado WiFi debil, respuestas debiles del cuestionario), y como solucionar cada cosa.
4. Termina invitandolo a seguir preguntando.
Usa UNICAMENTE los "Datos actuales del usuario"; no inventes hallazgos. Se breve."""


class SecurityBriefingService:
    """Redacta el mensaje inicial tras una evaluación; guardarlo es trabajo de ChatConversationService."""

    def __init__(self, engine: ChatEngine, prompt_builder: SecurityChatPromptBuilder) -> None:
        self._engine = engine
        self._prompt_builder = prompt_builder

    def write(self, owner_id: uuid.UUID, language: BriefingLanguage) -> str:
        system_prompt = self._prompt_builder.build(owner_id, topic="assessment_briefing")
        request = _BRIEFING_REQUEST.format(language=_LANGUAGE_NAMES[language])
        return to_plain_text(self._engine.complete(system_prompt, [ChatTurn("user", request)]))
