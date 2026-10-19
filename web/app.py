"""Flask Application factory for RalseiBot Web Dashboard."""
import logging
from pathlib import Path
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from web import config
from web.routes import bp

log = logging.getLogger(__name__)


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent
    template_dir = base_dir / "templates"
    static_dir = base_dir / "static"

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )

    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["JSON_AS_ASCII"] = False

    # Trust proxy headers on Vercel so HTTPS schemes, ports, and hosts are recognized correctly
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1,
    )

    # Register blueprints
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def page_not_found(e):
        try:
            return render_template("error.html", error_code=404, error_message="Página não encontrada."), 404
        except Exception:
            return "<h1>404 Página Não Encontrada</h1>", 404

    @app.errorhandler(403)
    def forbidden(e):
        try:
            return render_template("error.html", error_code=403, error_message="Acesso restrito a administradores."), 403
        except Exception:
            return "<h1>403 Acesso Negado</h1>", 403

    @app.errorhandler(500)
    def internal_error(e):
        try:
            return render_template("error.html", error_code=500, error_message="Ocorreu um erro interno no servidor."), 500
        except Exception as inner_e:
            log.exception("Failed to render error.html: %s", inner_e)
            return f"<h1>500 Erro Interno</h1><p>{e}</p>", 500

    @app.errorhandler(Exception)
    def handle_all_exceptions(e):
        import traceback
        log.exception("Unhandled application exception: %s", e)
        tb = traceback.format_exc()
        try:
            return render_template("error.html", error_code=500, error_message=str(e)), 500
        except Exception:
            return f"<!DOCTYPE html><html><body><h1>500 Erro na Aplicação</h1><p>{e}</p><pre>{tb}</pre></body></html>", 500

    return app
