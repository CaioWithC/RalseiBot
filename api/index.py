"""Vercel Serverless Function entry point for RalseiBot Dashboard."""
import sys
import traceback
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from flask import Flask

# Top-level AST assignment for Vercel detector
app = Flask(__name__)

try:
    from web.app import create_app
    app = create_app()

    # Wrap wsgi_app to catch and display any runtime exceptions cleanly
    _original_wsgi_app = app.wsgi_app

    def _safe_wsgi_app(environ, start_response):
        try:
            return _original_wsgi_app(environ, start_response)
        except Exception:
            err = traceback.format_exc()
            content = f"<!DOCTYPE html><html><body><h2>Flask Runtime Error</h2><pre>{err}</pre></body></html>"
            body = content.encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ])
            return [body]

    app.wsgi_app = _safe_wsgi_app

except Exception:
    _init_err = traceback.format_exc()

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        return f"<!DOCTYPE html><html><body><h2>Cold Start Error</h2><pre>{_init_err}</pre></body></html>", 200

application = app
handler = app
