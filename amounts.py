"""Exact coin amounts, suffixes, and aliases resolved when a bet is reserved."""
import re

from nextcord.ext import commands


def parse_amount(argument):
    value = argument.strip()
    if value.lower() in {"half", "all"}:
        return value.lower()
    if len(value) > 4096 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[kKmM]?", value):
        raise commands.BadArgument("Use um valor como 100, 10k, 1.5k, 1m, half ou all.")
    suffix = value[-1].lower()
    multiplier = {"k": 1_000, "m": 1_000_000}.get(suffix, 1)
    if suffix in {"k", "m"}:
        value = value[:-1]
    elif "." in value:
        raise commands.BadArgument("Sem k ou m, use um número inteiro de moedas.")
    whole, _, fraction = value.partition(".")
    # Integer arithmetic avoids rounding money through binary floats.
    amount, remainder = divmod(int(whole + fraction) * multiplier, 10 ** len(fraction))
    if amount <= 0 or remainder:
        raise commands.BadArgument("O valor deve representar um número inteiro de moedas maior que zero.")
    return amount


class BetAmount(commands.Converter):
    async def convert(self, ctx, argument):
        return parse_amount(argument)
