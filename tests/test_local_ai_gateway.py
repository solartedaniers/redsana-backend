"""Sin base: el gateway local entrega las mismas piezas del paquete que se usaban antes y siempre está listo."""

from redsana_ai import (
    ChatEngine,
    ChatTurn,
    EngineSecurityBriefing,
    EngineSecurityChat,
    IsolationForestAnomalyDetector,
    StreakOutageDetector,
)

from app.ai_gateway.local_ai_gateway import LocalAiGateway


class _EchoEngine(ChatEngine):
    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        return turns[-1].content


def test_chat_and_briefing_use_the_package_with_the_given_engine() -> None:
    gateway = LocalAiGateway(lambda: _EchoEngine())

    chat = gateway.security_chat()
    briefing = gateway.security_briefing()

    assert isinstance(chat, EngineSecurityChat)
    assert isinstance(briefing, EngineSecurityBriefing)
    assert chat.ask("- contexto", [], "hola") == "hola"


def test_detectors_are_the_package_defaults() -> None:
    gateway = LocalAiGateway(lambda: _EchoEngine())

    assert isinstance(gateway.anomaly_detector(), IsolationForestAnomalyDetector)
    assert isinstance(gateway.outage_detector(), StreakOutageDetector)


def test_detectors_do_not_build_a_chat_engine() -> None:
    def _unexpected_engine() -> ChatEngine:
        raise AssertionError("the detectors must not need a chat engine")

    gateway = LocalAiGateway(_unexpected_engine)

    gateway.anomaly_detector()
    gateway.outage_detector()


def test_local_ai_is_always_ready_and_warm_up_is_a_no_op() -> None:
    gateway = LocalAiGateway(lambda: _EchoEngine())

    gateway.start_warm_up()

    assert gateway.status() == "ready"
