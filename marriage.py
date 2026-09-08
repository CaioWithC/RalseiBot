"""Mutual marriage proposals, permanent ship scores and avatar cards."""
import asyncio
from io import BytesIO
import logging
import warnings

import nextcord
from nextcord.ext import commands
from PIL import Image, ImageDraw, ImageOps

from command_support import DualCommand
from db import database, EconomyError
from leaderboard import font, fit
from social import MAX_IMAGE_PIXELS

log = logging.getLogger(__name__)
PINK = 0xF29FB5
PROPOSAL_TIMEOUT = 120
SHIP_WIDTH, SHIP_HEIGHT = 1000, 680


def marriage_embed(record):
    timestamp = record["married_at"]
    embed = nextcord.Embed(title="💍 Casamento", color=PINK,
                          description=f"<@{record['first_id']}> 💞 <@{record['second_id']}>")
    embed.add_field(name="Data do casamento", value=f"<t:{timestamp}:F>", inline=False)
    embed.add_field(name="Tempo juntos", value=f"<t:{timestamp}:R>", inline=False)
    embed.set_footer(text="Dois corações, uma nova aventura.")
    return embed


async def read_avatar(user):
    try:
        asset = user.display_avatar.with_size(256).with_static_format("png")
        return await asyncio.wait_for(asset.read(), timeout=10)
    except (nextcord.HTTPException, asyncio.TimeoutError):
        return None


def render_ship(first_name, second_name, percentage, first_avatar=None, second_avatar=None):
    canvas = Image.new("RGB", (SHIP_WIDTH, SHIP_HEIGHT), "#111D29")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((24, 24, 976, 656), radius=30, fill="#1C2C3A", outline="#34505A", width=2)
    draw.text((500, 52), "RALSEI  /  SHIP", font=font(19, True), fill="#77E5BC", anchor="mt")
    draw.text((500, 87), "Dois corações, uma conexão", font=font(34, True), fill="#F6EDF2", anchor="mt")

    for x, name, data in ((270, first_name, first_avatar), (730, second_name, second_avatar)):
        draw.ellipse((x - 112, 159, x + 112, 383), fill="#F29FB5")
        portrait = None
        if data:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(data)) as source:
                        if source.width * source.height <= MAX_IMAGE_PIXELS:
                            portrait = ImageOps.fit(source.convert("RGBA"), (208, 208),
                                                    method=Image.Resampling.LANCZOS)
            except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                pass
        if portrait is not None:
            mask = Image.new("L", (208, 208))
            ImageDraw.Draw(mask).ellipse((0, 0, 207, 207), fill=255)
            base = Image.new("RGBA", (208, 208), "#253D49")
            base.alpha_composite(portrait)
            canvas.paste(base.convert("RGB"), (x - 104, 167), mask)
        else:
            draw.ellipse((x - 104, 167, x + 104, 375), fill="#253D49")
            initial = next((char.upper() for char in name if char.isalnum()), "?")
            draw.text((x, 271), initial, font=font(72, True), fill="#77E5BC", anchor="mm")
        name_font = font(26, True)
        draw.text((x, 403), fit(draw, name, name_font, 320), font=name_font, fill="#F6EDF2", anchor="mt")

    # Draw the heart as shapes so it renders even without an emoji font.
    draw.ellipse((457, 234, 501, 278), fill="#F29FB5")
    draw.ellipse((499, 234, 543, 278), fill="#F29FB5")
    draw.polygon(((460, 267), (540, 267), (500, 312)), fill="#F29FB5")
    draw.text((500, 450), f"{percentage}%", font=font(82, True), fill="#F29FB5", anchor="mt")
    draw.text((500, 545), "DE COMPATIBILIDADE", font=font(17, True), fill="#AFC5CC", anchor="mt")
    draw.rounded_rectangle((250, 582, 750, 594), radius=6, fill="#34505A")
    if percentage:
        draw.rounded_rectangle((250, 582, 250 + 5 * percentage, 594), radius=6, fill="#77E5BC")
    draw.text((500, 623), "Só uma brincadeira • A combinação deste par fica salva", font=font(16),
              fill="#AFC5CC", anchor="mt")
    output = BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output


class MarriageProposal(nextcord.ui.View):
    def __init__(self, first, second, *, storage, release):
        super().__init__(timeout=PROPOSAL_TIMEOUT)
        self.participants = (first.id, second.id)
        self.storage = storage
        self.release = release
        self.confirmed = set()
        self.lock = asyncio.Lock()
        self.message = None
        self.done = False
        self.result = None
        self.record = None

    def embed(self):
        if self.record is not None:
            return marriage_embed(self.record)
        embed = nextcord.Embed(title="💌 Pedido de casamento", color=PINK,
                              description=f"<@{self.participants[0]}> pediu <@{self.participants[1]}> em casamento!")
        for user_id in self.participants:
            state = "✅ Confirmou" if user_id in self.confirmed else "⏳ Aguardando confirmação"
            embed.add_field(name=state, value=f"<@{user_id}>", inline=True)
        if self.result:
            embed.add_field(name="Pedido encerrado", value=self.result, inline=False)
        else:
            embed.add_field(name="Vocês decidem", value="Ambos precisam clicar em Confirmar. Qualquer um pode recusar ou cancelar.", inline=False)
            embed.set_footer(text="Expira após 2 minutos sem interação. Enviar o pedido não conta como confirmação.")
        return embed

    def finish(self, result):
        self.done = True
        self.result = result
        for item in self.children:
            item.disabled = True
        self.stop()
        self.release(self)

    async def interaction_check(self, interaction):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("Só as duas pessoas deste pedido podem responder.", ephemeral=True)
            return False
        return True

    async def respond(self, interaction, *, accept):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send("Este pedido já foi encerrado.", ephemeral=True)
                return
            if not accept:
                self.finish(f"<@{interaction.user.id}> recusou ou cancelou o pedido.")
            else:
                if interaction.user.id in self.confirmed:
                    await interaction.followup.send("Você já confirmou. Aguarde a outra pessoa.", ephemeral=True)
                    return
                self.confirmed.add(interaction.user.id)
                self.confirm.label = f"Confirmar ({len(self.confirmed)}/2)"
                if len(self.confirmed) == 2:
                    try:
                        self.record = self.storage.marry(*self.participants)
                    except EconomyError as error:
                        self.finish(str(error))
                    else:
                        self.finish("As duas pessoas confirmaram. Felicidades!")
            await interaction.message.edit(embed=self.embed(), view=self)

    @nextcord.ui.button(label="Confirmar (0/2)", style=nextcord.ButtonStyle.success, emoji="💍")
    async def confirm(self, button, interaction):
        await self.respond(interaction, accept=True)

    @nextcord.ui.button(label="Recusar / cancelar", style=nextcord.ButtonStyle.danger)
    async def decline(self, button, interaction):
        await self.respond(interaction, accept=False)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            self.finish("O pedido expirou sem as duas confirmações. Envie um novo pedido para tentar novamente.")
            if self.message is not None:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except nextcord.HTTPException:
                    log.warning("Could not update expired marriage proposal")

    async def on_error(self, error, item, interaction):
        log.error("Marriage proposal failed", exc_info=(type(error), error, error.__traceback__))
        async with self.lock:
            if not self.done:
                self.finish("O pedido foi interrompido por um erro. Envie um novo pedido.")
        text = ("Não foi possível atualizar o pedido. Consulte `r.marriage` ou `/marriage` para ver o estado do casamento.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            if self.message is not None:
                await self.message.edit(embed=self.embed(), view=self)
        except nextcord.HTTPException:
            log.warning("Could not report failed marriage proposal")


class Relationships(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.proposals = {}
        self.image_jobs = asyncio.Semaphore(2)

    def release(self, view):
        for user_id in view.participants:
            if self.proposals.get(user_id) is view:
                del self.proposals[user_id]

    def cog_unload(self):
        for view in set(self.proposals.values()):
            view.stop()
        self.proposals.clear()

    @commands.command(cls=DualCommand, aliases=["casar", "propose"],
                      help="Peça alguém em casamento: r.marry @membro. As duas pessoas precisam confirmar nos botões.")
    @commands.guild_only()
    @commands.cooldown(1, 10, lambda message: message.author.id)
    async def marry(self, ctx, member: nextcord.Member):
        if ctx.author.id == member.id:
            raise EconomyError("Você não pode pedir a si mesmo em casamento.")
        if ctx.author.bot or member.bot:
            raise EconomyError("Bots não podem confirmar um casamento. Escolha outra pessoa.")
        for user_id in (ctx.author.id, member.id):
            if self.storage.marriage(user_id) is not None:
                raise EconomyError("Uma das pessoas já está casada. Veja com `r.marriage` ou `/marriage`.")
            if user_id in self.proposals:
                raise EconomyError("Uma das pessoas já tem um pedido em andamento. Aguarde ou cancele esse pedido.")
        view = MarriageProposal(ctx.author, member, storage=self.storage, release=self.release)
        for user_id in view.participants:
            self.proposals[user_id] = view
        try:
            view.message = await ctx.send(embed=view.embed(), view=view)
        except BaseException:
            view.finish("Não foi possível enviar o pedido.")
            raise

    @commands.command(cls=DualCommand, aliases=["shippar"],
                      help="r.ship @usuário ou r.ship @pessoa1 @pessoa2. Mostra avatares e uma porcentagem aleatória fixa para o par.")
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def ship(self, ctx, first: nextcord.User, second: nextcord.User = None):
        first, second = (ctx.author, first) if second is None else (first, second)
        percentage = self.storage.ship_score(first.id, second.id)
        async with self.image_jobs:
            avatars = await asyncio.gather(read_avatar(first), read_avatar(second))
            output = await asyncio.to_thread(render_ship, first.display_name, second.display_name, percentage, *avatars)
        try:
            await ctx.send(content=f"<@{first.id}> 💞 <@{second.id}>: **{percentage}%** de compatibilidade!",
                           file=nextcord.File(output, filename="ship.png"))
        finally:
            output.close()

    @commands.command(cls=DualCommand, aliases=["casamento", "married"],
                      help="Veja o casamento, a data e o tempo juntos: r.marriage [@usuário].")
    async def marriage(self, ctx, member: nextcord.User = None):
        target = member or ctx.author
        record = self.storage.marriage(target.id)
        if record is None:
            embed = nextcord.Embed(title="💍 Estado civil", color=PINK,
                                  description=f"Não há casamento registrado para <@{target.id}>.")
            embed.set_footer(text="Comece uma nova história com r.marry ou /marry.")
        else:
            embed = marriage_embed(record)
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Relationships(bot))
