import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

LIMITE_CORPO = 256 * 1024
USER_AGENT = "monitor-sites/1.0"


@dataclass(frozen=True)
class Resultado:
    ok: bool
    status: int | None
    tempo_ms: int | None
    erro: str | None


def validar_url(url: str) -> str:
    # urllib abre file:// e ftp:// sem reclamar. Numa ferramenta que o usuário alimenta com
    # endereços, deixar passar file:///etc/passwd seria ler arquivo local, não monitorar site.
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise ValueError(f"URL inválida: {url!r} (só aceito http:// ou https:// com endereço)")
    return url


def _ms(inicio: float) -> int:
    return round((time.perf_counter() - inicio) * 1000)


def _descrever_falha_de_rede(erro: BaseException) -> str:
    # URLError embrulha o erro de verdade em .reason
    motivo = erro.reason if isinstance(erro, urllib.error.URLError) else erro
    if isinstance(motivo, TimeoutError):
        return "timeout"
    if isinstance(motivo, ssl.SSLError):
        return f"erro de SSL: {motivo}"
    if isinstance(motivo, socket.gaierror):
        return "DNS: não achei o endereço"
    if isinstance(motivo, ConnectionRefusedError):
        return "conexão recusada"
    if isinstance(motivo, ConnectionResetError):
        return "conexão encerrada pelo servidor"
    return f"falha de rede: {motivo}"


def _status_aceito(status: int, esperado: int | None) -> bool:
    if esperado is not None:
        return status == esperado
    return 200 <= status < 400


def checar(url: str, timeout: float = 10.0, esperado: int | None = None,
           contem: str | None = None) -> Resultado:
    """Faz uma requisição GET e diz se o site está no ar.

    Considera no ar: status 2xx/3xx (ou exatamente `esperado`, se informado) e, se `contem`
    foi informado, o texto aparecendo nos primeiros 256 KB da resposta.
    """
    validar_url(url)
    inicio = time.perf_counter()
    requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            status = resposta.status
            corpo = resposta.read(LIMITE_CORPO) if contem else b""
    except urllib.error.HTTPError as e:
        # 4xx e 5xx chegam aqui como exceção, mas o servidor respondeu: o tempo e o status valem.
        # Redirecionamento em laço também (urllib desiste com um código 3xx), por isso aqui
        # "ok" só vale se o status bater exatamente com o esperado.
        tempo = _ms(inicio)
        ok = esperado is not None and e.code == esperado
        return Resultado(ok, e.code, tempo, None if ok else f"HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        # OSError cobre timeout e reset de conexão que estoura durante a leitura do corpo
        return Resultado(False, None, None, _descrever_falha_de_rede(e))

    tempo = _ms(inicio)
    if not _status_aceito(status, esperado):
        return Resultado(False, status, tempo, f"HTTP {status} (esperava {esperado})")
    if contem and contem not in corpo.decode("utf-8", errors="replace"):
        return Resultado(False, status, tempo, f"o texto {contem!r} não apareceu na resposta")
    return Resultado(True, status, tempo, None)
