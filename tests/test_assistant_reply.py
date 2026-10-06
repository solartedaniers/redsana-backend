from app.domain.assistant_reply import mentions_unexpected_dns, to_plain_text


def test_markdown_markers_are_removed_but_the_text_stays() -> None:
    reply = "## Resumen\nTu puntaje es **68/100**. Cierra el puerto `23` __hoy__."

    assert to_plain_text(reply) == "Resumen\nTu puntaje es 68/100. Cierra el puerto 23 hoy."


def test_the_real_wrong_dns_the_model_wrote_is_flagged() -> None:
    assert mentions_unexpected_dns("DNS primario: 1.1.1.3\nDNS secundario: 0.0.0.3")


def test_correct_family_dns_and_router_addresses_are_not_flagged() -> None:
    reply = "Entra a http://192.168.0.1 o 192.168.1.1 y escribe 1.1.1.3 y 1.0.0.3."

    assert not mentions_unexpected_dns(reply)


def test_any_other_public_dns_is_flagged() -> None:
    assert mentions_unexpected_dns("Usa 8.8.8.8 como secundario.")
    assert mentions_unexpected_dns("Escribe 1.0.0.1 en el secundario.")
