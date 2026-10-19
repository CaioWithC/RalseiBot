"""Vercel Serverless Function entry point for RalseiBot Dashboard."""
import os
import sys
import traceback
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from flask import Flask, jsonify

# Top-level AST assignment for Vercel detector
app = Flask(__name__)

try:
    from web.app import create_app
    app = create_app()

    @app.route("/api/diagnostics")
    def diagnostics():
        import os
        base_dir = Path(__file__).resolve().parent.parent
        web_dir = base_dir / "web"
        tpl_dir = web_dir / "templates"
        return jsonify({
            "status": "ok",
            "cwd": os.getcwd(),
            "cwd_files": os.listdir("."),
            "base_dir": str(base_dir),
            "base_dir_files": os.listdir(base_dir) if base_dir.exists() else [],
            "web_dir_exists": web_dir.exists(),
            "web_dir_files": os.listdir(web_dir) if web_dir.exists() else [],
            "tpl_dir_exists": tpl_dir.exists(),
            "tpl_dir_files": os.listdir(tpl_dir) if tpl_dir.exists() else [],
            "app_template_folder": app.template_folder,
            "app_static_folder": app.static_folder,
        })

    # Wrap wsgi_app to handle Vercel path rewrites and runtime errors
    _original_wsgi_app = app.wsgi_app

    def _safe_wsgi_app(environ, start_response):
        # Fix PATH_INFO if Vercel routed to /api/index
        forwarded_uri = environ.get("HTTP_X_FORWARDED_URI") or environ.get("HTTP_X_MATCHED_PATH")
        if forwarded_uri:
            environ["PATH_INFO"] = forwarded_uri.split("?")[0]
        elif environ.get("PATH_INFO") == "/api/index":
            environ["PATH_INFO"] = "/"
        elif environ.get("PATH_INFO", "").startswith("/api/index/"):
            environ["PATH_INFO"] = environ["PATH_INFO"][len("/api/index"):]

        try:
            return _original_wsgi_app(environ, start_response)
        except Exception:
            err = traceback.format_exc()
            content = f"<!DOCTYPE html><html><body><h2>Flask Runtime Error</h2><pre>{err}</pre></body></html>"
            body = content.encode("utf-8")
            start_response("500 Internal Server Error", [
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
