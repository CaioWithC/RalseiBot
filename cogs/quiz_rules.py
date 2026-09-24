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
    ("Qual é a capital da França?", ["Paris"]),
    ("Qual planeta é conhecido como Planeta Vermelho?", ["Marte"]),
    ("Quantos lados possui um hexágono?", ["6", "seis"]),
    ("Quem pintou a Mona Lisa?", ["Leonardo da Vinci", "Da Vinci"]),
    ("Qual é o menor país do mundo em termos de área?", ["Vaticano", "Cidade do Vaticano"]),
    ("Qual é o pais que tem a Pista de Monza?", ["Itália", "Italia"]),
    ("Qual cantor brasileiro é conhecido como Homem com H", ["Ney Matogrosso"]),
    ("Qual é o maior oceano do mundo?", ["Oceano Pacífico", "Pacífico", "Pacifico"]),
    ("Fale um continente qualquer:", ["África", "Ásia", "América do Norte", "América do Sul", "Antártida", "Europa", "Oceania"]),
    ("Em que continente fica o Egito?", ["África", "Africa"]),
    ("Qual é o símbolo químico da água?", ["H2O", "H₂O"]),
    ("Qual é o maior rio do mundo?", ["Nilo", "Nilo River"]),
    ("Quantos dias possui um ano comum?", ["365"]),
    ("Qual é o idioma oficial da China?", ["Mandarim"]),
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
