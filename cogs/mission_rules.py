"""Daily mission goals and bonus rewards, shared by storage and commands."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Mission:
    key: str
    title: str
    target: int
    reward: int


MISSIONS = (
    Mission("daily", "Boas-vindas ao reino", 1, 2500),
    Mission("work", "Um dia de trabalho", 1, 5000),
    Mission("freelance", "Talento independente", 3, 7500),
)
