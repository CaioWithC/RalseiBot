"""Anonymous confession posts with persistent buttons and staff attribution logs."""
import asyncio
from io import BytesIO
import logging

import nextcord
from nextcord.ext import commands
from PIL import Image, UnidentifiedImageError

from cogs.command_support import DualCommand
from db import EconomyError, database

log = logging.getLogger(__name__)
BUTTON_ID = "ralseibot:submit-confession"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}
DISCLOSURE = "Anônimo para os membros. A equipe recebe um registro com seu usuário e ID."


def validate_channels(guild, channel, log_channel):
    if any(not isinstance(item, nextcord.TextChannel) or item.guild.id != guild.id
           for item in (channel, log_channel)):
        raise EconomyError("Escolha dois canais de texto deste servidor.")
    if channel.id == log_channel.id:
        raise EconomyError("O canal de logs precisa ser diferente do canal de confissões.")
    if log_channel.permissions_for(guild.default_role).view_channel:
        raise EconomyError("O canal de logs deve ser privado: negue Ver Canal para @everyone e libere só a equipe.")
    for item in (channel, log_channel):
        permissions = item.permissions_for(guild.me) if guild.me else nextcord.Permissions.none()
        if not all((permissions.view_channel, permissions.send_messages,
                    permissions.embed_links, permissions.attach_files)):
            raise EconomyError("Preciso de Ver Canal, Enviar Mensagens, Inserir Links e Anexar Arquivos nos dois canais.")


def submission_values(data):
    # Label uses singular `component`, unlike the legacy ActionRow wrapper.
    inputs = {item["component"].get("custom_id"): item["component"]
              for item in data.get("components", []) if "component" in item}
    text = inputs.get("confession-text", {}).get("value", "").strip()
    if not text or len(text) > 4000:
        raise EconomyError("Escreva uma confissão com 1 a 4.000 caracteres.")
    files = inputs.get("confession-image", {}).get("values", [])
    if len(files) > 1:
        raise EconomyError("Envie no máximo uma imagem.")
    attachment = None
    if files:
        attachment = data.get("resolved", {}).get("attachments", {}).get(str(files[0]))
        if attachment is None:
            raise EconomyError("Não consegui encontrar a imagem. Abra o formulário e envie novamente.")
    return text, attachment


async def read_image(payload, interaction):
    if payload is None:
        return None, None
    limit = min(MAX_IMAGE_BYTES, interaction.guild.filesize_limit)
    if payload.get("size", 0) <= 0 or payload["size"] > limit:
        raise EconomyError(f"A imagem deve ter até {limit // (1024 * 1024)} MB.")
    attachment = nextcord.Attachment(data=payload, state=interaction._state)
    data = await attachment.read()
    if len(data) > limit:
        raise EconomyError("A imagem ultrapassa o limite de tamanho.")
    try:
        with Image.open(BytesIO(data)) as image:
            extension = IMAGE_EXTENSIONS.get(image.format)
            if extension is None or image.width * image.height > 16_000_000:
                raise EconomyError("Use PNG, JPG, GIF ou WebP com até 16 milhões de pixels.")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise EconomyError("Envie uma imagem PNG, JPG, GIF ou WebP válida.") from error
    # Do not expose the original filename, which may contain the author's name.
    return data, f"confession.{extension}"


class ConfessionModal(nextcord.ui.Modal):
    def __init__(self, cog, interaction, channels):
        super().__init__("Enviar confissão", timeout=600)
        self.cog = cog
        self.user_id = interaction.user.id
        self.guild_id = interaction.guild.id
        self.channels = channels
        self.lock = asyncio.Lock()
        self.submitted = False

    def to_components(self):
        # Nextcord 3.2 only supports TextInput children. Keep children empty so
        # its legacy state refresher leaves Label payloads alone; callback reads
        # the resolved data directly. send_modal still handles response/dispatch.
        # https://docs.discord.com/developers/components/reference#file-upload
        return [
            {"type": 10, "content": DISCLOSURE},
            {"type": 18, "label": "Escreva sua confissão:", "component": {
                "type": 4, "custom_id": "confession-text", "style": 2,
                "min_length": 1, "max_length": 4000, "required": True,
            }},
            {"type": 18, "label": "Imagem (opcional)",
             "description": "PNG, JPG, GIF ou WebP, até 8 MB e 16 milhões de pixels.",
             "component": {"type": 19, "custom_id": "confession-image",
                           "min_values": 0, "max_values": 1, "required": False}},
        ]

    async def callback(self, interaction):
        if (interaction.guild is None or interaction.guild.id != self.guild_id
                or interaction.user.id != self.user_id):
            await interaction.response.send_message("Abra seu próprio formulário no servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if self.submitted:
                await interaction.followup.send("Esta confissão já foi recebida.", ephemeral=True)
                return
            try:
                if self.cog.storage.confession_channels(self.guild_id) != self.channels:
                    raise EconomyError("A configuração mudou. Abra o formulário novamente.")
                channel, log_channel = [interaction.guild.get_channel(cid) for cid in self.channels]
                validate_channels(interaction.guild, channel, log_channel)
                if not channel.permissions_for(interaction.user).view_channel:
                    raise EconomyError("Você não tem acesso ao canal de confissões.")
                text, payload = submission_values(interaction.data)
                image_data, filename = await read_image(payload, interaction)
                number = self.cog.storage.reserve_confession(
                    self.guild_id, self.user_id, interaction.id, self.channels,
                )
            except EconomyError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            except nextcord.HTTPException:
                await interaction.followup.send("Não consegui baixar a imagem. Envie novamente.", ephemeral=True)
                return

            self.submitted = True
            embed = nextcord.Embed(title=f"Confissão anônima #{number}", description=text, color=0x9B59B6)
            audit = nextcord.Embed(title=f"Registro de confissão #{number}", description=text,
                                  color=0x9B59B6, timestamp=interaction.created_at)
            audit.add_field(name="Autor", value=f"{interaction.user.mention}\n{interaction.user}\nID: {self.user_id}", inline=False)
            audit.add_field(name="Destino", value=channel.mention, inline=False)
            audit.set_footer(text="Recebida; publicação pendente.")
            if filename:
                embed.set_image(url=f"attachment://{filename}")
                audit.set_image(url=f"attachment://{filename}")

            async def send(destination, post, **kwargs):
                file = nextcord.File(BytesIO(image_data), filename=filename) if image_data is not None else None
                try:
                    return await destination.send(embed=post, allowed_mentions=nextcord.AllowedMentions.none(),
                                                  **({"file": file} if file else {}), **kwargs)
                finally:
                    if file:
                        file.close()

            try:
                # A successful private log is required before any public post.
                log_message = await send(log_channel, audit)
            except nextcord.HTTPException:
                self.stop()
                await interaction.followup.send(
                    "Não consegui enviar o registro à equipe; sua confissão não foi publicada. "
                    "Avise um administrador e abra um novo formulário para tentar novamente.", ephemeral=True)
                return
            self.cog.storage.mark_confession(interaction.id, log_message_id=log_message.id)
            try:
                message = await send(channel, embed, view=ConfessionPanel(self.cog))
            except nextcord.HTTPException:
                audit.set_footer(text="Falha ao publicar no canal de confissões.")
                try:
                    await log_message.edit(embed=audit)
                except nextcord.HTTPException:
                    log.warning("Could not update confession log for guild %s, number %s", self.guild_id, number)
                self.stop()
                await interaction.followup.send(
                    "A equipe recebeu o registro, mas não consegui publicar a confissão. "
                    "Avise um administrador e abra um novo formulário para tentar novamente.", ephemeral=True)
                return

            self.stop()
            # The identity is already durable in SQLite and the private log.
            # Bookkeeping failures must not tell the author to repost a success.
            try:
                self.cog.storage.mark_confession(interaction.id, message_id=message.id)
                audit.add_field(name="Confissão publicada", value=message.jump_url, inline=False)
                audit.set_footer(text="Publicada. Identidade visível apenas neste registro privado.")
                await log_message.edit(embed=audit)
            except Exception:
                log.exception("Could not finalize confession log for guild %s, number %s", self.guild_id, number)
            await interaction.followup.send(f"Confissão #{number} enviada! {message.jump_url}", ephemeral=True)

    async def on_error(self, error, interaction):
        log.error("Confession submission failed", exc_info=(type(error), error, error.__traceback__))
        message = "Não consegui concluir o envio. Avise a equipe antes de tentar novamente."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class ConfessionPanel(nextcord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @nextcord.ui.button(label="Enviar confissão", style=nextcord.ButtonStyle.blurple, custom_id=BUTTON_ID)
    async def submit(self, button, interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este botão em um servidor.", ephemeral=True)
            return
        channels = self.cog.storage.confession_channels(interaction.guild.id)
        if channels is None or interaction.channel_id != channels[0]:
            await interaction.response.send_message("Este painel está desativado. Use o canal de confissões atual.", ephemeral=True)
            return
        await interaction.response.send_modal(ConfessionModal(self.cog, interaction, channels))


class Confessions(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.persistent_view = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self.persistent_view is None:
            self.persistent_view = ConfessionPanel(self)
            self.bot.add_view(self.persistent_view)

    def cog_unload(self):
        if self.persistent_view is not None:
            self.persistent_view.stop()

    @commands.command(cls=DualCommand, name="confess",
                      help="Administrador: r.confess #confissões #logs-privados publica o painel de confissões.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def confess(self, ctx, channel: nextcord.TextChannel, log_channel: nextcord.TextChannel):
        validate_channels(ctx.guild, channel, log_channel)
        embed = nextcord.Embed(title="Confissões anônimas", color=0x9B59B6,
                              description=f"Clique em **Enviar confissão** para escrever e anexar uma imagem opcional.\n\n{DISCLOSURE}")
        await channel.send(embed=embed, view=ConfessionPanel(self), allowed_mentions=nextcord.AllowedMentions.none())
        self.storage.configure_confessions(ctx.guild.id, channel.id, log_channel.id)
        await ctx.send(f"Painel de confissões enviado em {channel.mention}. Registros configurados no canal privado da equipe.")


def setup(bot):
    bot.add_cog(Confessions(bot))
