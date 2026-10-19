"""Configuration settings for RalseiBot Web Dashboard."""
import hashlib
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load root .env file if present
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Detect Vercel Environment
IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("VERCEL_URL"))

# Discord Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")

# Determine Default Redirect URI based on environment
if IS_VERCEL:
    # Use production Vercel domain requested: https://ralseibot.vercel.app/
    default_domain = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "ralseibot.vercel.app")
    DEFAULT_REDIRECT_URI = f"https://{default_domain}/callback"
else:
    DEFAULT_REDIRECT_URI = "http://localhost:5000/callback"

DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", DEFAULT_REDIRECT_URI)

# Flask Session Secret Key:
# In serverless environments (Vercel), ephemeral instances must share the same SECRET_KEY
# so user sessions survive across multiple requests.
_env_secret = os.getenv("SECRET_KEY")
if _env_secret:
    SECRET_KEY = _env_secret
elif DISCORD_TOKEN:
    SECRET_KEY = hashlib.sha256(f"ralseibot_session_{DISCORD_TOKEN}".encode()).hexdigest()
else:
    SECRET_KEY = "ralseibot_dashboard_session_key_production"

# Server Configuration
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
DEBUG = os.getenv("DASHBOARD_DEBUG", "false").lower() in ("true", "1", "yes")

# Base API URLs
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_CDN_BASE = "https://cdn.discordapp.com"
