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
    ("Quantos dias tem uma semana?", ["7"]),
    ("Qual é o maior animal do mundo?", ["Baleia-azul"]),
    ("Qual é o satélite natural da Terra?", ["Lua"]),
    ("Quanto é 5 + 7?", ["12", "10", "14"]),
    ("Qual animal é conhecido como rei da selva?", ["Leão"]),
    ("Quantas cores tem o arco-íris tradicionalmente?", ["7"]),
    ("Qual é o idioma oficial do Brasil?", ["Português"]),
    ("Qual é o maior planeta do Sistema Solar?", ["Júpiter"]),
    ("Em qual continente fica o Egito?", ["África"]),
    ("Qual é o resultado de 9 x 3?", ["27"]),
    ("Qual é o metal precioso de símbolo Au?", ["Ouro"]),
    ("Qual órgão bombeia o sangue?", ["Coração"]),
    ("Quantas horas tem um dia?", ["24"]),
    ("Qual é a estação mais fria do ano?", ["Inverno"]),
    ("Qual é o animal terrestre mais rápido?", ["Guepardo"]),
    ("Qual é a capital da França?", ["Paris"]),
    ("Qual é o resultado de 100 dividido por 10?", ["10"]),
    ("Qual gás os seres humanos precisam respirar para sobreviver?", ["Oxigênio"]),
    ("Quantos lados tem um triângulo?", ["3"]),
    ("Qual é a estrela mais próxima da Terra?", ["Sol"]),
    ("Qual é o maior continente do mundo?", ["Ásia"]),
    ("Que animal produz mel?", ["Abelha"]),
    ("Qual é a capital de Portugal?", ["Lisboa"]),
    ("Quantos meses tem um ano?", ["12"]),
    ("Qual é a cor resultante da mistura de azul com amarelo?", ["Verde"]),
    ("Qual é o primeiro mês do ano?", ["Janeiro"]),
    ("Qual é o principal ingrediente do pão tradicional?", ["Farinha", "Trigo"]),
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
