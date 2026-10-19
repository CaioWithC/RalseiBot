"""Vercel Serverless Function entry point for RalseiBot Dashboard."""
import sys
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

class WSGIHandler:
    def __init__(self):
        self._app = None
        self._error = None
        try:
            from web.app import create_app
            self._app = create_app()
        except Exception:
            import traceback
            self._error = traceback.format_exc()

    def __call__(self, environ, start_response):
        if self._error:
            content = f"<!DOCTYPE html><html><body><h2>Initialization Traceback:</h2><pre>{self._error}</pre></body></html>"
            body = content.encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body)))
            ])
            return [body]

        try:
            return self._app(environ, start_response)
        except Exception:
            import traceback
            err = traceback.format_exc()
            content = f"<!DOCTYPE html><html><body><h2>Runtime Traceback:</h2><pre>{err}</pre></body></html>"
            body = content.encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body)))
            ])
            return [body]


# Vercel Serverless top-level WSGI exports
app = WSGIHandler()
application = app
handler = app

