"""Único lugar donde el backend construye las piezas de redsana_ai; cambiar una implementación es tocar solo aquí."""
from redsana_ai import ChatEngine, EngineSecurityBriefing, EngineSecurityChat, GroqClient, SecurityBriefing, SecurityChat

from app.core.config import get_settings


def get_chat_engine() -> ChatEngine:
    # Va como dependencia aparte para poder reemplazarla en las pruebas sin llamar a la API real de Groq.
    settings = get_settings()
    return GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        temperature=settings.groq_temperature,
        api_url=settings.groq_api_url,
    )


def build_security_chat(engine: ChatEngine) -> SecurityChat:
    return EngineSecurityChat(engine)


def build_security_briefing(engine: ChatEngine) -> SecurityBriefing:
    return EngineSecurityBriefing(engine)
