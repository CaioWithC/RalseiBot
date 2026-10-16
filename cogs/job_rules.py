"""Job and freelance definitions, availability schedules, and leveling mechanics."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

DAILY_TIMEZONE = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    emoji: str
    category: str  # "work" ou "freelance"
    start_hour: int
    end_hour: int
    min_reward: int
    max_reward: int
    description: str

    @property
    def hours_display(self) -> str:
        if self.start_hour == 0 and self.end_hour == 24:
            return "24 Horas"
        return f"{self.start_hour:02d}:00 às {self.end_hour:02d}:00"

    def is_available(self, hour: int) -> bool:
        if self.start_hour == 0 and self.end_hour == 24:
            return True
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        # Overnight window, e.g. 18 to 2 or 22 to 8
        return hour >= self.start_hour or hour < self.end_hour


LEVELS: Tuple[Tuple[int, int, str, float], ...] = (
    (1, 0, "Iniciante", 0.0),
    (2, 3, "Júnior", 0.15),
    (3, 8, "Pleno", 0.35),
    (4, 15, "Sênior", 0.60),
    (5, 25, "Mestre", 1.00),
)


WORK_JOBS = (
    Job("barista", "Barista de Cafeteria", "☕", "work", 6, 14, 12000, 26000,
        "Prepara cafés especiais e atende os clientes matinais."),
    Job("entregador", "Entregador Matutino", "📦", "work", 7, 13, 13000, 28000,
        "Organiza encomendas expressas e distribui pacotes."),
    Job("atendente", "Atendente Comercial", "💼", "work", 9, 18, 15000, 32000,
        "Atende clientes no balcão e resolve chamados de suporte."),
    Job("dev", "Desenvolvedor de Software", "💻", "work", 12, 20, 18000, 40000,
        "Codifica novas funcionalidades e resolve bugs no sistema."),
    Job("designer", "Designer Gráfico", "🎨", "work", 13, 21, 16000, 36000,
        "Cria conceitos visuais, ilustrações e layouts de publicidade."),
    Job("barman", "Barman Noturno", "🍸", "work", 18, 2, 20000, 42000,
        "Mistura coquetéis refinados no agito noturno da cidade."),
    Job("seguranca", "Segurança Patrimonial", "🛡️", "work", 20, 6, 22000, 44000,
        "Faz rondas de vigia e monitora as câmeras do prédio."),
    Job("plantonista", "Plantonista Noturno", "🏥", "work", 22, 8, 24000, 48000,
        "Atendimento emergencial e cuidados na escala da madrugada."),
    Job("caixa", "Operador de Caixa 24h", "🏪", "work", 0, 24, 11000, 24000,
        "Atendimento rápido no balcão da loja de conveniência."),
)

FREELANCE_JOBS = (
    Job("paes", "Entrega de Pães Matinais", "🥐", "freelance", 5, 12, 800, 3500,
        "Entrega pães quentinhos e croissants pela vizinhança."),
    Job("dogwalker", "Passeador de Cães", "🐕", "freelance", 7, 17, 1000, 4800,
        "Passeia com cãezinhos no parque em manhãs e tardes ensolaradas."),
    Job("formatacao", "Formatação de Computador", "🔧", "freelance", 9, 18, 1800, 6800,
        "Instala sistemas operacionais e remove vírus de computadores."),
    Job("logo", "Design de Logotipo Express", "🎨", "freelance", 12, 19, 2200, 8000,
        "Cria arte vetorial e identidade visual rápida para um cliente."),
    Job("pizza", "Entregador de Pizza", "🍕", "freelance", 18, 2, 2000, 7500,
        "Entrega caixas de pizza quentinhas de moto pela cidade."),
    Job("dj", "DJ de Festa Universitária", "🎧", "freelance", 19, 3, 2800, 9500,
        "Comanda o som e mixa faixas animadas na pista de dança."),
    Job("moderador", "Moderação Noturna de Stream", "🦉", "freelance", 22, 6, 1800, 7200,
        "Mantém a ordem no bate-papo de criadores durante madrugadas."),
    Job("carreto", "Descarga e Carreto Noturno", "🚚", "freelance", 0, 7, 2500, 8500,
        "Ajuda na conferência e descarregamento de fardos no depósito."),
    Job("redacao", "Redação de Artigos Web", "📝", "freelance", 0, 24, 1000, 5000,
        "Escreve pequenos resumos e responde formulários online."),
)

ALL_JOBS = WORK_JOBS + FREELANCE_JOBS


def get_available_jobs(category: str, hour: int) -> List[Job]:
    """Return all jobs of a category open at the given hour (0-23)."""
    jobs = WORK_JOBS if category == "work" else FREELANCE_JOBS
    return [job for job in jobs if job.is_available(hour)]


def find_job(category: str, identifier: str) -> Optional[Job]:
    """Find a job by ID or partial title match."""
    if not identifier:
        return None
    normalized = identifier.strip().lower()
    jobs = WORK_JOBS if category == "work" else FREELANCE_JOBS

    # 1. Exact ID match
    for job in jobs:
        if job.id.lower() == normalized:
            return job

    # 2. Exact or substring title match
    for job in jobs:
        if normalized in job.title.lower():
            return job

    return None


def calculate_level(xp: int) -> int:
    """Determine level from current XP."""
    current_level = 1
    for lvl, threshold, _, _ in LEVELS:
        if xp >= threshold:
            current_level = lvl
    return current_level


def get_level_info(xp: int) -> Tuple[int, str, float, int, Optional[int], int]:
    """Return (level, rank_title, bonus_multiplier, xp, next_threshold, prev_threshold)."""
    level = calculate_level(xp)
    for i, (lvl, threshold, title, bonus) in enumerate(LEVELS):
        if lvl == level:
            next_threshold = LEVELS[i + 1][1] if i + 1 < len(LEVELS) else None
            prev_threshold = threshold
            return level, title, bonus, xp, next_threshold, prev_threshold
    return 1, "Iniciante", 0.0, xp, 3, 0


def format_progress_bar(xp: int, length: int = 10) -> str:
    """Format visual XP progress bar."""
    level, title, bonus, current_xp, next_threshold, prev_threshold = get_level_info(xp)
    if next_threshold is None:
        return "▰" * length + " (Nível Máximo!)"

    span = max(1, next_threshold - prev_threshold)
    progress = max(0, min(1.0, (current_xp - prev_threshold) / span))
    filled = int(round(progress * length))
    bar = "▰" * filled + "▱" * (length - filled)
    return f"{bar} ({current_xp}/{next_threshold} XP)"


def get_shift_info(hour: int) -> Tuple[str, str]:
    """Return friendly shift name and emoji for an hour."""
    if 6 <= hour < 12:
        return "Manhã", "🌅"
    elif 12 <= hour < 18:
        return "Tarde", "☀️"
    elif 18 <= hour < 24:
        return "Noite", "🌙"
    else:
        return "Madrugada", "🌌"

