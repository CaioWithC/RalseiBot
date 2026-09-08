"""Discord slash options; all behavior lives in the matching prefix command."""
import nextcord
from nextcord.ext import commands

from command_support import InteractionContext
from sendmessage import EmbedJSONModal

GUILD_ONLY = [nextcord.InteractionContextType.guild]
ADMIN = nextcord.Permissions(administrator=True)
BET_DESCRIPTION = "Aposta: 100, 10k, 1.5m, half ou all (até seu saldo)."


class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def invoke(self, interaction, name, *, attachments=(), **options):
        ctx = InteractionContext(self.bot, interaction, self.bot.get_command(name), options, attachments)
        await interaction.response.defer()
        # Bot.invoke runs the original command's checks and shared cooldowns.
        await self.bot.invoke(ctx)

    @nextcord.slash_command(name="ping", description="Verifica se o bot está online.")
    async def ping(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "ping")

    @nextcord.slash_command(name="help", description="Lista os comandos r. e /, ou mostra a ajuda de um comando.")
    async def help(self, interaction: nextcord.Interaction,
                   command: str = nextcord.SlashOption(description="Ex.: mines, pay ou profile background.", required=False)):
        await self.invoke(interaction, "help", command=command)

    @nextcord.slash_command(name="sync", description="Administrador: sincroniza os comandos de barra com o Discord.",
                            contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def sync(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "sync")

    @nextcord.slash_command(name="send", description="Administrador: envia uma mensagem pelo bot.",
                            contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def send(self, interaction: nextcord.Interaction,
                   message: str = nextcord.SlashOption(description="Mensagem que o bot enviará.")):
        await self.invoke(interaction, "send", message=message)

    @nextcord.slash_command(name="embedsend", description="Administrador: envia um embed através de JSON.",
                            contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def embedsend(self, interaction: nextcord.Interaction):
        await interaction.response.send_modal(EmbedJSONModal())

    @nextcord.slash_command(name="ticket", description="Administrador: publica um painel de tickets.",
                            contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def ticket(self, interaction: nextcord.Interaction,
                     category: nextcord.CategoryChannel = nextcord.SlashOption(
                         description="Categoria onde os tickets serão criados.",
                         channel_types=[nextcord.ChannelType.category])):
        await self.invoke(interaction, "ticket", category=category)

    @nextcord.slash_command(name="balance", description="Mostra seu saldo em DarkMoney.")
    async def balance(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "balance")

    @nextcord.slash_command(name="daily", description="Receba sua recompensa diária em DarkMoney. Renova às 00:00 (GMT-3).")
    async def daily(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "daily")

    @nextcord.slash_command(name="work", description="Trabalhe para ganhar DarkMoney a cada 2 horas.", contexts=GUILD_ONLY)
    async def work(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "work")

    @nextcord.slash_command(name="freelance", description="Faça um 'freelance' para ganhar DarkMoney a cada 10 minutos.", contexts=GUILD_ONLY)
    async def freelance(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "freelance")

    @nextcord.slash_command(name="rob", description="Roube DarkMoney de outro membro a cada 60 minutos.", contexts=GUILD_ONLY)
    async def rob(self, interaction: nextcord.Interaction,
    member: nextcord.Member = nextcord.SlashOption(description="Membro que será roubado.")):
        await self.invoke(interaction, "rob", member=member)

    @nextcord.slash_command(name="pay", description="Transfira DarkMoney para outro membro.", contexts=GUILD_ONLY)
    async def pay(self, interaction: nextcord.Interaction,
                  member: nextcord.Member = nextcord.SlashOption(description="Membro que receberá as moedas."),
                  amount: str = nextcord.SlashOption(description="Quantidade inteira de moedas. Ex.: 100.")):
        await self.invoke(interaction, "pay", member=member, amount=amount)

    @nextcord.slash_command(name="addbalance", description="Administrador: adicione DarkMoney a um membro.",
                           contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def addbalance(self, interaction: nextcord.Interaction,
                         member: nextcord.Member = nextcord.SlashOption(description="Membro que receberá as moedas."),
                         amount: str = nextcord.SlashOption(description="Quantidade inteira de moedas para adicionar.")):
        await self.invoke(interaction, "addbalance", member=member, amount=amount)

    @nextcord.slash_command(name="setbalance", description="Administrador: defina o saldo de um membro.",
                           contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def setbalance(self, interaction: nextcord.Interaction,
                         member: nextcord.Member = nextcord.SlashOption(description="Membro cujo saldo será alterado."),
                         amount: str = nextcord.SlashOption(description="Novo saldo inteiro em DarkMoney.")):
        await self.invoke(interaction, "setbalance", member=member, amount=amount)

    @nextcord.slash_command(name="resetbalance", description="Administrador: zere o saldo de um membro.",
                           contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def resetbalance(self, interaction: nextcord.Interaction,
                           member: nextcord.Member = nextcord.SlashOption(description="Membro cujo saldo será zerado.")):
        await self.invoke(interaction, "resetbalance", member=member)

    @nextcord.slash_command(name="activity", description="Administrador: defina uma atividade por 5 minutos ou use reset para voltar à rotação.",
                           contexts=GUILD_ONLY, default_member_permissions=ADMIN)
    async def activity(self, interaction: nextcord.Interaction,
                       text: str = nextcord.SlashOption(description="Atividade de até 128 caracteres, ou reset para retomar a rotação.",
                                                        min_length=1, max_length=128)):
        await self.invoke(interaction, "activity", text=text)

    @nextcord.slash_command(name="rich", description="Ranking global em imagem, com 10 jogadores por página.")
    async def rich(self, interaction: nextcord.Interaction,
                   page: int = nextcord.SlashOption(description="Página do ranking.", default=1, min_value=1, max_value=1_000_000)):
        await self.invoke(interaction, "rich", page=page)

    @nextcord.slash_command(name="slots", description="Gire três rolos e aposte DarkMoney.")
    async def slots(self, interaction: nextcord.Interaction,
                    amount: str = nextcord.SlashOption(description=BET_DESCRIPTION)):
        await self.invoke(interaction, "slots", amount=amount)

    @nextcord.slash_command(name="blackjack", description="Jogue blackjack com botões e aposte DarkMoney.")
    async def blackjack(self, interaction: nextcord.Interaction,
                        amount: str = nextcord.SlashOption(description=BET_DESCRIPTION)):
        await self.invoke(interaction, "blackjack", amount=amount)

    @nextcord.slash_command(name="mines", description="Revele casas seguras e retire seus ganhos antes de encontrar uma mina.")
    async def mines(self, interaction: nextcord.Interaction,
                    amount: str = nextcord.SlashOption(description=BET_DESCRIPTION),
                    mine_count: int = nextcord.SlashOption(description="Quantidade de minas; omita para escolher no menu.",
                                                           required=False, min_value=1, max_value=15)):
        await self.invoke(interaction, "mines", amount=amount, mine_count=mine_count)

    @nextcord.slash_command(name="marry", description="Peça alguém em casamento. As duas pessoas precisam confirmar nos botões.", contexts=GUILD_ONLY)
    async def marry(self, interaction: nextcord.Interaction,
                    member: nextcord.Member = nextcord.SlashOption(description="Pessoa que receberá o pedido de casamento.")):
        await self.invoke(interaction, "marry", member=member)

    @nextcord.slash_command(name="ship", description="Veja os avatares e a porcentagem de compatibilidade fixa de duas pessoas.")
    async def ship(self, interaction: nextcord.Interaction,
                   first: nextcord.User = nextcord.SlashOption(description="Pessoa para shippar com você, ou a primeira pessoa do par."),
                   second: nextcord.User = nextcord.SlashOption(description="Segunda pessoa do par; omita para shippar você com a primeira.", required=False)):
        await self.invoke(interaction, "ship", first=first, second=second)

    @nextcord.slash_command(name="marriage", description="Veja o casamento de alguém, a data e o tempo juntos.")
    async def marriage(self, interaction: nextcord.Interaction,
                       member: nextcord.User = nextcord.SlashOption(description="Usuário a consultar; omita para ver seu próprio casamento.", required=False)):
        await self.invoke(interaction, "marriage", member=member)

    @nextcord.slash_command(name="profile", description="Veja e personalize seu perfil.")
    async def profile(self, interaction: nextcord.Interaction):
        pass  # Discord requires a subcommand when the command has children.

    @profile.subcommand(name="view", description="Veja seu perfil ou o de outro usuário em imagem.")
    async def profile_view(self, interaction: nextcord.Interaction,
                           member: nextcord.User = nextcord.SlashOption(description="Usuário do perfil; omita para ver o seu.", required=False)):
        await self.invoke(interaction, "profile", member=member)

    @profile.subcommand(name="color", description="Altere a cor dos painéis do seu perfil.")
    async def profile_color(self, interaction: nextcord.Interaction,
                            value: str = nextcord.SlashOption(description="Cor hexadecimal de seis dígitos. Ex.: #77E5BC.")):
        await self.invoke(interaction, "profile color", value=value)

    @profile.subcommand(name="about", description="Altere seu Sobre mim; use reset para limpar.")
    async def profile_about(self, interaction: nextcord.Interaction,
                            text: str = nextcord.SlashOption(description="Texto de até 300 caracteres, ou reset.", min_length=1, max_length=300)):
        await self.invoke(interaction, "profile about", text=text)

    @profile.subcommand(name="background", description="Envie uma imagem de fundo (até 8 MB) ou remova a atual.")
    async def profile_background(self, interaction: nextcord.Interaction,
                                 image: nextcord.Attachment = nextcord.SlashOption(description="Imagem PNG, JPG, WebP ou GIF.", required=False),
                                 action: str = nextcord.SlashOption(description="Selecione reset para remover o fundo.", required=False, choices=["reset"])):
        await self.invoke(interaction, "profile background", attachments=[image] if image else [], action=action)


def setup(bot):
    bot.add_cog(SlashCommands(bot))
