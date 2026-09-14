"""Quiz defaults and exact matching after harmless spelling normalization."""
import unicodedata

MIN_INTERVAL = 30 * 60
MAX_INTERVAL = 60 * 60
ACTIVITY_WINDOW = 10 * 60
MIN_MESSAGES = 5
MIN_PARTICIPANTS = 2
ROUND_SECONDS = 120
DEFAULT_REWARD = 1000

SEED_QUESTIONS = (
    ("Quanto é 7 × 8?", ["56"]),
    ("Quanto é 144 dividido por 12?", ["12"]),
    ("Qual é a raiz quadrada de 81?", ["9"]),
    ("Quem é o criador da teoria do gato na caixa?", ["Erwin Schrödinger", "Schrödinger", "Schrodinger"]),
    ("Complete a sequência: 2, 4, 8, 16, …", ["32"]),
    ("Quanto é 15% de 200?", ["30"]),
    ("Quantos minutos há em duas horas e meia?", ["150"]),
    ("Qual é o país onde vivemos?", ["Brasil"]),
    ("Quem é o meu criador?", ["Caio"]),
    ("Qual é o resultado de (3 + 5) × 2?", ["16"]),
    ("Quanto é 20 + 20 + 20 + 7?", ["67", "Six-Seven", "six seven"])
)


def normalize_answer(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.split()).strip(" .!?\"'“”‘’")


def suggestion_answers(answer, aliases=""):
    values = list(dict.fromkeys(text.strip() for text in [answer, *aliases.splitlines()] if text.strip()))
    if not values or len(values) > 10 or any(not normalize_answer(text) or len(text) > 100 for text in values):
        raise ValueError("Informe uma resposta válida e até 9 alternativas, uma por linha, com até 100 caracteres cada.")
    return values
