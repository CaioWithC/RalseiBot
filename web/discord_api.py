"""Discord API interactions and OAuth2 authentication helper."""
import base64
import logging
import time
import requests
from typing import Dict, List, Optional, Set, Tuple

from web import config

log = logging.getLogger(__name__)

# In-memory caches to avoid hitting Discord rate limits
_cache: Dict[str, Tuple[float, any]] = {}
CACHE_TTL = 30  # seconds


def _get_cached(key: str):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None


def _set_cached(key: str, val: any):
    _cache[key] = (time.time(), val)


def get_bot_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bot {config.DISCORD_TOKEN}",
        "User-Agent": "RalseiBot-Dashboard (https://github.com/RalseiBot, 1.0)",
    }


def get_bot_info() -> Dict:
    """Fetches bot user information."""
    cached = _get_cached("bot_info")
    if cached is not None:
        return cached

    if not config.DISCORD_TOKEN:
        return {"id": "", "username": "Ralsei", "avatar": None}

    try:
        res = requests.get(f"{config.DISCORD_API_BASE}/users/@me", headers=get_bot_headers(), timeout=5)
        if res.status_code == 200:
            data = res.json()
            _set_cached("bot_info", data)
            return data
    except Exception as e:
        log.warning("Could not fetch bot info: %s", e)

    return {"id": "", "username": "Ralsei", "avatar": None}


def get_client_id() -> str:
    """Resolves Discord Client ID from config or Bot user ID."""
    if config.DISCORD_CLIENT_ID:
        return config.DISCORD_CLIENT_ID

    bot_info = get_bot_info()
    if bot_info.get("id"):
        return str(bot_info["id"])

    # Fallback attempt: decode the first part of the bot token
    if config.DISCORD_TOKEN and "." in config.DISCORD_TOKEN:
        try:
            part = config.DISCORD_TOKEN.split(".")[0]
            padded = part + "=" * ((4 - len(part) % 4) % 4)
            decoded = base64.b64decode(padded).decode("utf-8")
            if decoded.isdigit():
                return decoded
        except Exception:
            pass

    return ""


def get_bot_guilds() -> List[Dict]:
    """Fetches list of guilds where the bot is currently present."""
    cached = _get_cached("bot_guilds")
    if cached is not None:
        return cached

    if not config.DISCORD_TOKEN:
        return []

    try:
        res = requests.get(f"{config.DISCORD_API_BASE}/users/@me/guilds", headers=get_bot_headers(), timeout=6)
        if res.status_code == 200:
            data = res.json()
            _set_cached("bot_guilds", data)
            return data
        log.warning("Failed to fetch bot guilds: HTTP %s: %s", res.status_code, res.text)
    except Exception as e:
        log.error("Exception fetching bot guilds: %s", e)

    return []


def get_bot_guild_ids() -> Set[str]:
    """Returns set of guild IDs where the bot is installed."""
    return {str(g["id"]) for g in get_bot_guilds()}


def get_guild_details(guild_id: str) -> Optional[Dict]:
    """Fetches details for a specific guild where the bot is present."""
    key = f"guild_details_{guild_id}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    if not config.DISCORD_TOKEN:
        return None

    try:
        res = requests.get(
            f"{config.DISCORD_API_BASE}/guilds/{guild_id}?with_counts=true",
            headers=get_bot_headers(),
            timeout=6,
        )
        if res.status_code == 200:
            data = res.json()
            _set_cached(key, data)
            return data
    except Exception as e:
        log.error("Exception fetching guild details for %s: %s", guild_id, e)

    return None


def get_guild_channels(guild_id: str) -> Dict[str, List[Dict]]:
    """Fetches and categorizes channels of a guild."""
    key = f"guild_channels_{guild_id}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    result = {
        "text_channels": [],
        "categories": [],
        "all": [],
    }

    if not config.DISCORD_TOKEN:
        return result

    try:
        res = requests.get(
            f"{config.DISCORD_API_BASE}/guilds/{guild_id}/channels",
            headers=get_bot_headers(),
            timeout=6,
        )
        if res.status_code == 200:
            channels = res.json()
            result["all"] = channels
            # Type 0 = GUILD_TEXT, Type 5 = GUILD_ANNOUNCEMENT
            result["text_channels"] = sorted(
                [c for c in channels if c.get("type") in (0, 5)],
                key=lambda x: (x.get("position", 0), x.get("name", "")),
            )
            # Type 4 = GUILD_CATEGORY
            result["categories"] = sorted(
                [c for c in channels if c.get("type") == 4],
                key=lambda x: (x.get("position", 0), x.get("name", "")),
            )
            _set_cached(key, result)
            return result
    except Exception as e:
        log.error("Exception fetching channels for guild %s: %s", guild_id, e)

    return result


def exchange_code(code: str) -> Optional[Dict]:
    """Exchanges OAuth2 authorization code for Discord access token."""
    client_id = get_client_id()
    if not client_id or not config.DISCORD_CLIENT_SECRET:
        log.error("Missing DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET for OAuth2 token exchange.")
        return None

    payload = {
        "client_id": client_id,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        res = requests.post(
            f"{config.DISCORD_API_BASE}/oauth2/token",
            data=payload,
            headers=headers,
            timeout=8,
        )
        if res.status_code == 200:
            return res.json()
        log.error("OAuth token exchange failed (%s): %s", res.status_code, res.text)
    except Exception as e:
        log.error("Exception exchanging OAuth code: %s", e)

    return None


def get_user_profile(access_token: str) -> Optional[Dict]:
    """Fetches the authenticated Discord user's profile."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(f"{config.DISCORD_API_BASE}/users/@me", headers=headers, timeout=6)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        log.error("Exception fetching user profile: %s", e)
    return None


def get_user_guilds(access_token: str) -> List[Dict]:
    """Fetches all guilds the authenticated user belongs to."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(f"{config.DISCORD_API_BASE}/users/@me/guilds", headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        log.error("Exception fetching user guilds: %s", e)
    return []


def is_admin_or_owner(guild: Dict) -> bool:
    """Verifies if the user is the owner or has Administrator permission (bit 0x8)."""
    if guild.get("owner") is True:
        return True
    try:
        perms = int(guild.get("permissions", 0))
        # Administrator permission bitflag is 0x8 (8)
        return (perms & 0x8) != 0
    except (ValueError, TypeError):
        return False


def filter_admin_guilds(user_guilds: List[Dict]) -> List[Dict]:
    """Filters guilds to only those where the user is an administrator or owner."""
    return [g for g in user_guilds if is_admin_or_owner(g)]


def get_invite_url(guild_id: Optional[str] = None) -> str:
    """Generates the OAuth2 invite link to add the bot to a server."""
    client_id = get_client_id()
    # Scopes: bot, applications.commands; Permissions: 8 (Administrator)
    url = (
        f"https://discord.com/oauth2/authorize?client_id={client_id}"
        f"&permissions=8&scope=bot%20applications.commands"
    )
    if guild_id:
        url += f"&guild_id={guild_id}&disable_guild_select=true"
    return url


def get_oauth_login_url(state: str = "") -> str:
    """Generates the Discord OAuth2 authorization URL for user login."""
    client_id = get_client_id()
    from urllib.parse import quote
    redirect_uri_encoded = quote(config.DISCORD_REDIRECT_URI, safe="")
    url = (
        f"https://discord.com/oauth2/authorize?client_id={client_id}"
        f"&response_type=code&redirect_uri={redirect_uri_encoded}"
        f"&scope=identify%20guilds"
    )
    if state:
        url += f"&state={quote(state, safe='')}"
    return url


def get_avatar_url(user: Dict) -> str:
    """Constructs avatar URL for a user."""
    if not user:
        return f"{config.DISCORD_CDN_BASE}/embed/avatars/0.png"
    user_id = user.get("id")
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"{config.DISCORD_CDN_BASE}/avatars/{user_id}/{avatar}.{ext}?size=128"
    # Default Discord avatar
    discriminator = int(user.get("discriminator", 0))
    if discriminator != 0:
        index = discriminator % 5
    else:
        index = (int(user_id) >> 22) % 6 if user_id else 0
    return f"{config.DISCORD_CDN_BASE}/embed/avatars/{index}.png"


def get_guild_icon_url(guild: Dict) -> Optional[str]:
    """Constructs icon URL for a guild."""
    guild_id = guild.get("id")
    icon = guild.get("icon")
    if icon and guild_id:
        ext = "gif" if icon.startswith("a_") else "png"
        return f"{config.DISCORD_CDN_BASE}/icons/{guild_id}/{icon}.{ext}?size=128"
    return None

