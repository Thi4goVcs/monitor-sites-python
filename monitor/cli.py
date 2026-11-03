import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

from .banco import Banco, SiteJaExiste
from .verificador import Resultado, checar, validar_url

BANCO_PADRAO = "monitor.db"

SAIDA_OK = 0
SAIDA_FALHA_NO_SITE = 1
SAIDA_USO_INCORRETO = 2


def _hora_local(texto_iso: str) -> str:
    return datetime.fromisoformat(texto_iso).astimezone().strftime("%d/%m %H:%M:%S")


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
    colunas = list(zip(cabecalho, *linhas)) if linhas else [(c,) for c in cabecalho]
    larguras = [max(len(str(celula)) for celula in coluna) for coluna in colunas]
    formatar = lambda linha: "  ".join(str(c).ljust(l) for c, l in zip(linha, larguras)).rstrip()
    return "\n".join([formatar(cabecalho)] + [formatar(l) for l in linhas])


def _ms(valor: int | None) -> str:
    return "-" if valor is None else f"{valor} ms"


def cmd_adicionar(args, banco: Banco) -> int:
    try:
        url = validar_url(args.url)
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return SAIDA_USO_INCORRETO

    nome = args.nome or urlparse(url).netloc
    try:
        site_id = banco.adicionar_site(nome, url, args.esperado, args.contem)
    except SiteJaExiste:
        print(f"Erro: {url} já está cadastrado.", file=sys.stderr)
        return SAIDA_USO_INCORRETO
    print(f"Cadastrado: [{site_id}] {nome} ({url})")
    return SAIDA_OK


def cmd_listar(args, banco: Banco) -> int:
    sites = banco.listar_sites()
    if not sites:
        print("Nenhum site cadastrado.")
        return SAIDA_OK
    linhas = [[s.id, s.nome, s.url, s.esperado or "2xx/3xx", s.contem or "-"] for s in sites]
    print(_tabela(["id", "nome", "url", "status esperado", "deve conter"], linhas))
    return SAIDA_OK


def cmd_remover(args, banco: Banco) -> int:
    if not banco.remover_site(args.id):
        print(f"Erro: não existe site com id {args.id}.", file=sys.stderr)
        return SAIDA_USO_INCORRETO
    print(f"Removido o site {args.id} (e o histórico dele).")
    return SAIDA_OK


def _linha_da_checagem(site, resultado: Resultado) -> str:
    hora = datetime.now().strftime("%H:%M:%S")
    if resultado.ok:
        return f"[{hora}] OK      {resultado.status}  {_ms(resultado.tempo_ms):>8}  {site.nome}"
    detalhe = resultado.erro
    return f"[{hora}] FALHOU  {resultado.status or '-'}  {_ms(resultado.tempo_ms):>8}  {site.nome}: {detalhe}"


def cmd_checar(args, banco: Banco) -> int:
    houve_falha = False
    rodada = 0

    try:
        while True:
            sites = banco.listar_sites()
            if not sites:
                print("Nenhum site cadastrado. Use: python -m monitor adicionar <url>", file=sys.stderr)
                return SAIDA_USO_INCORRETO

            # As requisições rodam em paralelo (o tempo de uma rodada é o do site mais lento,
            # não a soma). A escrita no banco fica só na thread principal, depois: assim não
            # tem conexão do SQLite sendo usada por thread diferente da que a criou.
            with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
                resultados = list(pool.map(
                    lambda s: checar(s.url, args.timeout, s.esperado, s.contem), sites))

            for site, resultado in zip(sites, resultados):
                banco.registrar(site.id, resultado)
                print(_linha_da_checagem(site, resultado))
                houve_falha = houve_falha or not resultado.ok

            rodada += 1
            if args.repetir is None or (args.vezes and rodada >= args.vezes):
                break
            time.sleep(args.repetir)
    except KeyboardInterrupt:
        print("\nParado.")
        return SAIDA_OK

    return SAIDA_FALHA_NO_SITE if houve_falha else SAIDA_OK


def cmd_resumo(args, banco: Banco) -> int:
    resumos = banco.resumo(args.horas)
    if not resumos:
        print("Nenhum site cadastrado.")
        return SAIDA_OK

    linhas = []
    for r in resumos:
        uptime = "sem dados" if r.uptime_pct is None else f"{r.uptime_pct:.2f}%"
        linhas.append([r.site.id, r.site.nome, uptime, f"{r.ok}/{r.total}",
                       _ms(r.tempo_medio_ms), _ms(r.p95_ms)])

    print(f"Últimas {args.horas:g} hora(s):\n")
    print(_tabela(["id", "nome", "uptime", "ok/total", "média", "p95"], linhas))

    falhas = [r for r in resumos if r.ultima_falha]
    if falhas:
        print("\nÚltima falha de cada site:")
        for r in falhas:
            print(f"  {r.site.nome}: {_hora_local(r.ultima_falha)} ({r.ultimo_erro})")
    return SAIDA_OK


def cmd_historico(args, banco: Banco) -> int:
    site = banco.buscar_site(args.id)
    if site is None:
        print(f"Erro: não existe site com id {args.id}.", file=sys.stderr)
        return SAIDA_USO_INCORRETO

    checagens = banco.historico(args.id, args.limite)
    if not checagens:
        print(f"{site.nome}: ainda sem checagens.")
        return SAIDA_OK

    print(f"{site.nome} ({site.url}), mais recentes primeiro:\n")
    linhas = [[_hora_local(c.verificado_em), "OK" if c.ok else "FALHOU", c.status or "-",
               _ms(c.tempo_ms), c.erro or ""] for c in checagens]
    print(_tabela(["quando", "resultado", "status", "tempo", "erro"], linhas))
    return SAIDA_OK


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitor", description="Monitor simples de sites: checa, guarda o histórico e resume o uptime.")
    parser.add_argument("--banco", default=BANCO_PADRAO,
                        help=f"arquivo SQLite com os dados (padrão: {BANCO_PADRAO})")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("adicionar", help="cadastra um site")
    p.add_argument("url")
    p.add_argument("--nome", help="nome de exibição (padrão: o endereço do site)")
    p.add_argument("--esperado", type=int, metavar="STATUS",
                   help="status HTTP que significa 'no ar' (padrão: qualquer 2xx/3xx)")
    p.add_argument("--contem", metavar="TEXTO",
                   help="texto que precisa aparecer na página (pega erro que volta com status 200)")
    p.set_defaults(funcao=cmd_adicionar)

    p = sub.add_parser("listar", help="mostra os sites cadastrados")
    p.set_defaults(funcao=cmd_listar)

    p = sub.add_parser("remover", help="remove um site e o histórico dele")
    p.add_argument("id", type=int)
    p.set_defaults(funcao=cmd_remover)

    p = sub.add_parser("checar", help="checa todos os sites agora")
    p.add_argument("--timeout", type=float, default=10.0, help="segundos por tentativa (padrão: 10)")
    p.add_argument("--paralelo", type=int, default=8, help="requisições ao mesmo tempo (padrão: 8)")
    p.add_argument("--repetir", type=float, metavar="SEGUNDOS",
                   help="fica checando de novo a cada N segundos (Ctrl+C para parar)")
    p.add_argument("--vezes", type=int, default=0,
                   help="com --repetir, para depois de N rodadas (padrão: 0 = infinito)")
    p.set_defaults(funcao=cmd_checar)

    p = sub.add_parser("resumo", help="uptime e tempo de resposta por site")
    p.add_argument("--horas", type=float, default=24, help="janela de tempo (padrão: 24)")
    p.set_defaults(funcao=cmd_resumo)

    p = sub.add_parser("historico", help="últimas checagens de um site")
    p.add_argument("id", type=int)
    p.add_argument("--limite", type=int, default=20)
    p.set_defaults(funcao=cmd_historico)

    return parser


def main(argv: list[str] | None = None) -> int:
    # No Windows o console usa a codepage do sistema por padrão e os acentos saem corrompidos
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")

    args = criar_parser().parse_args(argv)
    if getattr(args, "paralelo", 1) < 1:
        print("Erro: --paralelo precisa ser pelo menos 1.", file=sys.stderr)
        return SAIDA_USO_INCORRETO
    with Banco(args.banco) as banco:
        return args.funcao(args, banco)
