"""Entrypoint to run the RalseiBot Web Dashboard server."""
import logging
import sys
from web import config
from web.app import create_app
from web.discord_api import get_bot_info, get_client_id

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
)
log = logging.getLogger("dashboard")


def main():
    app = create_app()

    bot_info = get_bot_info()
    client_id = get_client_id()

    banner = rf"""
  ╔══════════════════════════════════════════════════════════════╗
  ║                ✨ RALSEIBOT WEB DASHBOARD ✨                 ║
  ║        Painel de Configuração de Servidores e Comandos       ║
  ╚══════════════════════════════════════════════════════════════╝

  🤖 Bot Conectado:  {bot_info.get('username', 'RalseiBot')}
  🆔 Client ID:      {client_id or 'Não detectado'}
  🌐 Endereço Local: http://localhost:{config.PORT}
  🔗 Endereço Rede:  http://127.0.0.1:{config.PORT}
  
  🔒 Segurança: Apenas Administradores e Donos dos servidores
                podem visualizar e alterar configurações.
  
  💡 Pressione CTRL+C para encerrar o servidor web.
"""
    print(banner)

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
    )


if __name__ == "__main__":
    main()

