import re

# Detecta cuando el usuario ESCRIBE una contraseña, no cuando pregunta por ella. Se evalúa antes de
# guardar o enviar: si coincide, el texto nunca llega a la base ni al modelo externo.
_SECRET_WORDS = r"\b(contrase(?:ñ|n)a|clave|password|passwd|pwd|pass)"
_QUALIFIER = r"(?:\s+(?:de|del|of|for|to)\s+[\wáéíóúñ-]+(?:\s+[\wáéíóúñ-]+)?)?"
_ASSIGNMENT = r"\s*(?:(?:es|era|sería|is|was)\s*[:=]?|[:=])\s*"
_VALUE = r"[\"'«“]?(?P<value>[^\s\"'»”?¿.,;!]{3,})"
_DISCLOSURE = re.compile(_SECRET_WORDS + _QUALIFIER + _ASSIGNMENT + _VALUE, re.IGNORECASE)

# Palabras que, justo después de "es", indican una pregunta sobre la contraseña y no la contraseña en sí.
_DESCRIPTIVE_WORDS = {
    "segura", "seguro", "fuerte", "debil", "débil", "buena", "mala", "correcta", "incorrecta",
    "suficiente", "corta", "larga", "nueva", "vieja", "igual", "misma", "valida", "válida",
    "muy", "demasiado", "la", "el", "una", "un", "mi", "tu", "su",
    "secure", "strong", "weak", "good", "bad", "correct", "wrong", "enough", "short", "long",
    "new", "old", "same", "valid", "too", "very", "the", "a", "an", "my", "your",
}


def contains_password_disclosure(message: str) -> bool:
    for match in _DISCLOSURE.finditer(message):
        if match.group("value").lower() not in _DESCRIPTIVE_WORDS:
            return True
    return False
