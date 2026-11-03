import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from monitor.banco import Banco


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia o log de cada requisição nos testes
        pass

    def _responder(self, status, corpo=b"", extras=None):
        self.send_response(status)
        for chave, valor in (extras or {}).items():
            self.send_header(chave, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho == "/ok":
            self._responder(200, b"tudo certo")
        elif caminho == "/pagina":
            self._responder(200, "Bem-vindo ao sistema".encode())
        elif caminho == "/acentos":
            self._responder(200, "Olá, mundo — ação".encode())
        elif caminho == "/erro-com-200":
            self._responder(200, b"Internal Server Error: banco fora do ar")
        elif caminho == "/erro":
            self._responder(500, b"quebrou")
        elif caminho == "/naoexiste":
            self._responder(404, b"nada aqui")
        elif caminho == "/privado":
            self._responder(401, b"login")
        elif caminho == "/redireciona":
            self._responder(302, extras={"Location": "/ok"})
        elif caminho == "/laco":
            self._responder(302, extras={"Location": "/laco"})
        elif caminho == "/lento":
            time.sleep(0.6)
            self._responder(200, b"devagar")
        elif caminho == "/travado":
            time.sleep(3)
            self._responder(200, b"tarde demais")
        elif caminho == "/enorme":
            # o texto procurado só aparece depois do limite de leitura
            self._responder(200, b"x" * (300 * 1024) + b"FIM")
        else:
            self._responder(404)


@pytest.fixture(scope="session")
def servidor():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def porta_fechada():
    # abre uma porta, anota o número e fecha: ninguém está escutando nela
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{porta}"


@pytest.fixture
def banco(tmp_path):
    with Banco(str(tmp_path / "teste.db")) as b:
        yield b
