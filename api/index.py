"""Vercel Serverless Function entry point for RalseiBot Dashboard."""
import sys
import traceback
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from web.app import create_app
    app = create_app()
except Exception as e:
    import logging
    logging.exception("Failed to initialize Flask app for Vercel: %s", e)
    from flask import Flask
    error_trace = traceback.format_exc()
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        return f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
          <meta charset="UTF-8">
          <title>Erro de Inicialização · RalseiBot</title>
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0B1319; color: #F8FAFC; padding: 40px; line-height: 1.6; }}
            .container {{ max-width: 800px; margin: 0 auto; background: #121F29; border: 1px solid rgba(248, 113, 113, 0.3); border-radius: 12px; padding: 32px; }}
            h1 {{ color: #F87171; margin-top: 0; font-size: 1.5rem; }}
            pre {{ background: #080E13; border: 1px solid rgba(255, 255, 255, 0.1); padding: 16px; border-radius: 8px; color: #FCA5A5; overflow-x: auto; font-size: 0.9rem; }}
          </style>
        </head>
        <body>
          <div class="container">
            <h1>⚠️ Falha na Inicialização da Aplicação</h1>
            <p>Ocorreu o seguinte erro durante o cold-start do servidor no Vercel:</p>
            <pre>{error_trace}</pre>
          </div>
        </body>
        </html>
        """, 500
