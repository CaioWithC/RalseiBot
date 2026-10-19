"""Vercel Serverless Function entry point for RalseiBot Dashboard."""
import sys
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from web.app import create_app

# Vercel Serverless top-level WSGI exports
app = create_app()
application = app
handler = app
