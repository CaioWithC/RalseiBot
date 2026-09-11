"""Let prefix and slash commands use the same Nextcord invocation pipeline."""
from types import SimpleNamespace

from nextcord.ext import commands
from nextcord.ext.commands.view import StringView


class InteractionContext(commands.Context):
    def __init__(self, bot, interaction, command, options, attachments=()):
        # Prefix checks, cooldowns and existing upload handlers expect a message.
        message = SimpleNamespace(
            id=interaction.id, author=interaction.user, guild=interaction.guild,
            channel=interaction.channel, attachments=list(attachments), content="",
            created_at=interaction.created_at, edited_at=None, _state=bot._connection,
        )
        super().__init__(message=message, bot=bot, view=StringView(""), prefix="/",
                         command=command, invoked_with=command.name)
        self.interaction = interaction
        self.options = options

    async def send(self, content=None, **kwargs):
        # The slash entry point defers first. wait=True returns an editable message
        # for game buttons and automatic settlements on timeout.
        return await self.interaction.followup.send(content=content, wait=True, **kwargs)


class _DualArguments:
    async def _parse_arguments(self, ctx):
        if not isinstance(ctx, InteractionContext):
            return await super()._parse_arguments(ctx)

        ctx.args = [ctx] if self.cog is None else [self.cog, ctx]
        ctx.kwargs = {}
        for name, param in self.clean_params.items():
            ctx.current_parameter = param
            if name in ctx.options:
                value = ctx.options[name]
                # Discord resolves users, attachments and numeric options. Text
                # still uses the prefix converters (including BetAmount and int).
                if isinstance(value, str):
                    converter = param.annotation if param.annotation is not param.empty else str
                    value = await commands.run_converters(ctx, converter, value, param)
            elif param.default is not param.empty:
                value = param.default
            else:
                raise commands.MissingRequiredArgument(param)
            if param.kind == param.KEYWORD_ONLY:
                ctx.kwargs[name] = value
            else:
                ctx.args.append(value)


class DualCommand(_DualArguments, commands.Command):
    """Keep checks, cooldowns, converters, hooks and errors shared across inputs."""


class DualGroup(_DualArguments, commands.Group):
    """A prefix group whose base callback also accepts resolved slash options."""


def slash_name(command):
    return "profile view" if command.qualified_name == "profile" else command.qualified_name
