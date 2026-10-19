"""Web routes and API endpoints for RalseiBot Dashboard."""
import functools
import logging
import secrets
import time
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import database
from web import config, discord_api
from web.command_data import COMMAND_METADATA, CATEGORIES_INFO

log = logging.getLogger(__name__)
bp = Blueprint("dashboard", __name__)


def login_required(view):
    """Decorator to require Discord login."""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get("user"):
            return redirect(url_for("dashboard.login", next=request.path))
        return view(**kwargs)
    return wrapped_view


def get_user_admin_guilds() -> list:
    """Returns the list of guilds the logged-in user can administer."""
    # Check session cache
    if "admin_guilds" in session:
        return session["admin_guilds"]

    user = session.get("user")
    if not user:
        return []

    # Dev mode simulated guilds
    if session.get("is_dev_login"):
        bot_guilds = discord_api.get_bot_guilds()
        # Simulated admin access to all connected bot guilds + 1 sample unadded guild
        guilds = []
        for g in bot_guilds:
            guilds.append({
                "id": str(g["id"]),
                "name": g.get("name", "Servidor"),
                "icon": g.get("icon"),
                "owner": True,
                "permissions": "2147483647",
            })
        if not guilds:
            guilds.append({
                "id": "123456789012345678",
                "name": "Castelo das Trevas",
                "icon": None,
                "owner": True,
                "permissions": "8",
            })
        session["admin_guilds"] = guilds
        return guilds

    access_token = session.get("access_token")
    if not access_token:
        return []

    raw_guilds = discord_api.get_user_guilds(access_token)
    admin_guilds = discord_api.filter_admin_guilds(raw_guilds)
    session["admin_guilds"] = admin_guilds
    return admin_guilds


def user_can_manage_guild(guild_id: str) -> bool:
    """Verifies if the logged-in user is an admin or owner of this guild."""
    guild_id = str(guild_id)
    guilds = get_user_admin_guilds()
    for g in guilds:
        if str(g.get("id")) == guild_id:
            return discord_api.is_admin_or_owner(g)
    return False


@bp.route("/")
def index():
    """Homepage / Landing page."""
    bot_info = discord_api.get_bot_info()
    bot_guilds = discord_api.get_bot_guilds()
    user = session.get("user")
    invite_url = discord_api.get_invite_url()

    return render_template(
        "index.html",
        bot_info=bot_info,
        bot_guilds_count=len(bot_guilds),
        user=user,
        invite_url=invite_url,
    )


@bp.route("/login")
def login():
    """Discord OAuth2 login entry point."""
    next_page = request.args.get("next", url_for("dashboard.dashboard_view"))
    session["next_page"] = next_page

    client_id = discord_api.get_client_id()
    client_secret = config.DISCORD_CLIENT_SECRET

    # If OAuth2 Client Secret is not yet provided, show the friendly setup / dev guide
    if not client_secret or not client_id:
        return render_template(
            "login_help.html",
            client_id=client_id,
            redirect_uri=config.DISCORD_REDIRECT_URI,
        )

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    oauth_url = discord_api.get_oauth_login_url(state=state)
    return redirect(oauth_url)


@bp.route("/dev-login")
def dev_login():
    """Development / Testing login bypass for local review."""
    bot_info = discord_api.get_bot_info()
    session["user"] = {
        "id": "999999999999999999",
        "username": "Administrador Local",
        "global_name": "Admin Dev",
        "avatar": None,
        "avatar_url": discord_api.get_avatar_url(None),
    }
    session["is_dev_login"] = True
    session.pop("admin_guilds", None)
    flash("Conectado no modo de demonstração/desenvolvimento!", "info")
    return redirect(session.pop("next_page", url_for("dashboard.dashboard_view")))


@bp.route("/callback")
def callback():
    """Discord OAuth2 callback handler."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        flash(f"Autorização cancelada ou recusada: {error}", "danger")
        return redirect(url_for("dashboard.index"))

    if not code:
        flash("Nenhum código de autorização foi fornecido.", "danger")
        return redirect(url_for("dashboard.index"))

    token_data = discord_api.exchange_code(code)
    if not token_data or "access_token" not in token_data:
        flash("Falha ao comunicar com a API do Discord para autenticação.", "danger")
        return redirect(url_for("dashboard.index"))

    access_token = token_data["access_token"]
    user_data = discord_api.get_user_profile(access_token)

    if not user_data:
        flash("Não foi possível carregar suas informações de perfil do Discord.", "danger")
        return redirect(url_for("dashboard.index"))

    user_data["avatar_url"] = discord_api.get_avatar_url(user_data)
    session["user"] = user_data
    session["access_token"] = access_token
    session.pop("admin_guilds", None)  # refresh cached guilds

    flash(f"Bem-vindo(a), {user_data.get('global_name') or user_data.get('username')}!", "success")
    next_page = session.pop("next_page", url_for("dashboard.dashboard_view"))
    return redirect(next_page)


@bp.route("/logout")
def logout():
    """Log out of the dashboard."""
    session.clear()
    flash("Você encerrou a sessão com sucesso.", "info")
    return redirect(url_for("dashboard.index"))


@bp.route("/dashboard")
@bp.route("/servers")
@login_required
def dashboard_view():
    """Dashboard view listing all eligible guilds for the logged-in user."""
    user_guilds = get_user_admin_guilds()
    bot_guild_ids = discord_api.get_bot_guild_ids()

    eligible_guilds = []
    for g in user_guilds:
        gid = str(g["id"])
        has_bot = gid in bot_guild_ids
        eligible_guilds.append({
            "id": gid,
            "name": g.get("name", "Servidor"),
            "icon_url": discord_api.get_guild_icon_url(g),
            "owner": g.get("owner", False),
            "has_bot": has_bot,
            "invite_url": discord_api.get_invite_url(gid),
            "config_url": url_for("dashboard.guild_view", guild_id=gid),
        })

    # Sort: servers with bot first, then alphabetical by name
    eligible_guilds.sort(key=lambda x: (not x["has_bot"], x["name"].lower()))

    return render_template(
        "dashboard.html",
        user=session.get("user"),
        guilds=eligible_guilds,
        total_count=len(eligible_guilds),
        active_count=sum(1 for g in eligible_guilds if g["has_bot"]),
        invite_general=discord_api.get_invite_url(),
    )


@bp.route("/guild/<guild_id>")
@login_required
def guild_view(guild_id: str):
    """Server configuration panel."""
    guild_id = str(guild_id)

    # Security check: User must be admin or owner
    if not user_can_manage_guild(guild_id):
        flash("Você precisa ser Administrador ou Dono deste servidor para configurá-lo.", "danger")
        return redirect(url_for("dashboard.dashboard_view"))

    bot_guild_ids = discord_api.get_bot_guild_ids()
    has_bot = guild_id in bot_guild_ids

    # Find guild basic info from user guilds
    user_guilds = get_user_admin_guilds()
    guild_info = next((g for g in user_guilds if str(g["id"]) == guild_id), None)
    if not guild_info:
        guild_info = {"id": guild_id, "name": f"Servidor {guild_id}", "icon": None}

    guild_name = guild_info.get("name", "Servidor")
    guild_icon_url = discord_api.get_guild_icon_url(guild_info)

    # If the bot is not yet in the server, provide the invite option
    if not has_bot:
        invite_url = discord_api.get_invite_url(guild_id)
        return render_template(
            "guild_invite.html",
            user=session.get("user"),
            guild_id=guild_id,
            guild_name=guild_name,
            guild_icon_url=guild_icon_url,
            invite_url=invite_url,
        )

    # Fetch guild details and channels
    guild_channels = discord_api.get_guild_channels(guild_id)
    text_channels = guild_channels.get("text_channels", [])
    categories = guild_channels.get("categories", [])

    # Fetch current configs from database
    settings = database.get_guild_settings(guild_id)
    confessions = database.get_confession_config(guild_id) or {}
    tickets = database.get_ticket_config(guild_id) or {}
    quiz = database.get_quiz_config(guild_id) or {}

    disabled_commands = set(settings.get("disabled_commands", []))
    disabled_categories = set(settings.get("disabled_categories", []))

    # Prepare command data grouped by category
    commands_by_category = {}
    for cat_key, cat_data in CATEGORIES_INFO.items():
        cat_commands = []
        for cmd_name, cmd_info in COMMAND_METADATA.items():
            if cmd_info.get("cat") == cat_key:
                is_disabled = (cmd_name in disabled_commands) or (cat_key in disabled_categories)
                cat_commands.append({
                    "name": cmd_name,
                    "desc": cmd_info.get("desc", ""),
                    "protected": cmd_info.get("protected", False),
                    "enabled": not is_disabled,
                })
        commands_by_category[cat_key] = {
            "info": cat_data,
            "category_enabled": cat_key not in disabled_categories,
            "commands": sorted(cat_commands, key=lambda c: c["name"]),
        }

    return render_template(
        "guild.html",
        user=session.get("user"),
        guild_id=guild_id,
        guild_name=guild_name,
        guild_icon_url=guild_icon_url,
        settings=settings,
        confessions=confessions,
        tickets=tickets,
        quiz=quiz,
        text_channels=text_channels,
        categories=categories,
        commands_by_category=commands_by_category,
        categories_info=CATEGORIES_INFO,
    )


# =========================================================================
# REST API Endpoints
# =========================================================================

@bp.route("/api/guild/<guild_id>/settings", methods=["POST"])
@login_required
def api_save_settings(guild_id: str):
    """API endpoint to save general server and command configurations."""
    guild_id = str(guild_id)
    if not user_can_manage_guild(guild_id):
        return jsonify({"error": "Permissão negada. Você não é administrador deste servidor."}), 403

    data = request.get_json(silent=True) or request.form.to_dict()

    update_args = {}
    if "prefix" in data:
        raw_prefix = str(data["prefix"]).strip()[:10]
        update_args["prefix"] = raw_prefix if raw_prefix else "r."

    if "disabled_commands" in data:
        update_args["disabled_commands"] = list(data["disabled_commands"])

    if "disabled_categories" in data:
        update_args["disabled_categories"] = list(data["disabled_categories"])

    if "mod_log_channel_id" in data:
        update_args["mod_log_channel_id"] = data["mod_log_channel_id"]

    if "welcome_channel_id" in data:
        update_args["welcome_channel_id"] = data["welcome_channel_id"]

    if "welcome_message" in data:
        update_args["welcome_message"] = data["welcome_message"]

    saved = database.update_guild_settings(guild_id, **update_args)
    return jsonify({"success": True, "message": "Configurações salvas com sucesso!", "settings": saved})


@bp.route("/api/guild/<guild_id>/confessions", methods=["POST"])
@login_required
def api_save_confessions(guild_id: str):
    """API endpoint to configure confession channels."""
    guild_id = str(guild_id)
    if not user_can_manage_guild(guild_id):
        return jsonify({"error": "Permissão negada."}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    channel_id = str(data.get("channel_id", "")).strip()
    log_channel_id = str(data.get("log_channel_id", "")).strip()

    if not channel_id or not log_channel_id:
        return jsonify({"error": "Selecione o canal de confissões e o canal de logs."}), 400

    try:
        database.configure_confessions(guild_id, channel_id, log_channel_id)
        return jsonify({"success": True, "message": "Módulo de confissões configurado com sucesso!"})
    except Exception as e:
        log.error("Error saving confessions: %s", e)
        return jsonify({"error": f"Erro ao salvar: {str(e)}"}), 500


@bp.route("/api/guild/<guild_id>/tickets", methods=["POST"])
@login_required
def api_save_tickets(guild_id: str):
    """API endpoint to configure ticket category."""
    guild_id = str(guild_id)
    if not user_can_manage_guild(guild_id):
        return jsonify({"error": "Permissão negada."}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    category_id = str(data.get("category_id", "")).strip()

    if not category_id:
        return jsonify({"error": "Selecione a categoria para os tickets."}), 400

    try:
        database.configure_tickets(guild_id, category_id)
        return jsonify({"success": True, "message": "Categoria de tickets atualizada com sucesso!"})
    except Exception as e:
        log.error("Error saving tickets: %s", e)
        return jsonify({"error": f"Erro ao salvar: {str(e)}"}), 500


@bp.route("/api/guild/<guild_id>/quiz", methods=["POST"])
@login_required
def api_save_quiz(guild_id: str):
    """API endpoint to configure automated trivia quiz."""
    guild_id = str(guild_id)
    if not user_can_manage_guild(guild_id):
        return jsonify({"error": "Permissão negada."}), 403

    data = request.get_json(silent=True) or request.form.to_dict()
    enabled = bool(data.get("enabled", True))

    if not enabled:
        database.disable_quiz(guild_id)
        return jsonify({"success": True, "message": "Quiz automático desativado."})

    channel_id = str(data.get("channel_id", "")).strip()
    review_channel_id = str(data.get("review_channel_id", "")).strip()
    reward = int(data.get("reward", 100))

    if not channel_id or not review_channel_id:
        return jsonify({"error": "Selecione o canal do quiz e o canal de moderação."}), 400

    if reward < 1 or reward > 100_000:
        return jsonify({"error": "A recompensa deve ser entre 1 e 100.000 D$."}), 400

    try:
        database.configure_quiz(guild_id, channel_id, review_channel_id, reward, next_at=int(time.time() + 60))
        return jsonify({"success": True, "message": "Quiz automático configurado e ativado!"})
    except Exception as e:
        log.error("Error saving quiz: %s", e)
        return jsonify({"error": f"Erro ao salvar: {str(e)}"}), 500


@bp.route("/api/guild/<guild_id>/reset-prefix", methods=["POST"])
@login_required
def api_reset_prefix(guild_id: str):
    """API endpoint to reset prefix to default 'r.'."""
    guild_id = str(guild_id)
    if not user_can_manage_guild(guild_id):
        return jsonify({"error": "Permissão negada."}), 403

    database.update_guild_settings(guild_id, prefix="r.")
    return jsonify({"success": True, "message": "Prefixo redefinido para 'r.'", "prefix": "r."})

