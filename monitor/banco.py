import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .verificador import Resultado

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL,
    url       TEXT NOT NULL UNIQUE,
    esperado  INTEGER,
    contem    TEXT
);

CREATE TABLE IF NOT EXISTS checagens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id        INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    verificado_em  TEXT NOT NULL,
    ok             INTEGER NOT NULL,
    status         INTEGER,
    tempo_ms       INTEGER,
    erro           TEXT
);

CREATE INDEX IF NOT EXISTS idx_checagens_site_data ON checagens (site_id, verificado_em);
"""


class SiteJaExiste(Exception):
    pass


@dataclass(frozen=True)
class Site:
    id: int
    nome: str
    url: str
    esperado: int | None
    contem: str | None


@dataclass(frozen=True)
class Checagem:
    verificado_em: str
    ok: bool
    status: int | None
    tempo_ms: int | None
    erro: str | None


@dataclass(frozen=True)
class ResumoSite:
    site: Site
    total: int
    ok: int
    uptime_pct: float | None
    tempo_medio_ms: int | None
    p95_ms: int | None
    ultima_falha: str | None
    ultimo_erro: str | None


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _texto_da_data(momento: datetime) -> str:
    # Sempre UTC e sempre o mesmo formato: assim comparar as datas como texto no SQL
    # dá a mesma ordem que comparar datas de verdade.
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def percentil(valores: list[int], p: float) -> int | None:
    """Percentil pelo método do posto mais próximo: o menor valor que cobre p% das amostras."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = math.ceil(p / 100 * len(ordenados)) - 1
    return ordenados[max(posicao, 0)]


class Banco:
    def __init__(self, caminho: str):
        self._conexao = sqlite3.connect(caminho)
        self._conexao.row_factory = sqlite3.Row
        # SQLite ignora chave estrangeira por padrão: sem isso o ON DELETE CASCADE não roda
        self._conexao.execute("PRAGMA foreign_keys = ON")
        self._conexao.executescript(ESQUEMA)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def fechar(self):
        self._conexao.close()

    # --- sites ---

    @staticmethod
    def _site(linha: sqlite3.Row) -> Site:
        return Site(linha["id"], linha["nome"], linha["url"], linha["esperado"], linha["contem"])

    def adicionar_site(self, nome: str, url: str, esperado: int | None = None,
                       contem: str | None = None) -> int:
        try:
            with self._conexao:
                cursor = self._conexao.execute(
                    "INSERT INTO sites (nome, url, esperado, contem) VALUES (?, ?, ?, ?)",
                    (nome, url, esperado, contem),
                )
        except sqlite3.IntegrityError:
            raise SiteJaExiste(url) from None
        return cursor.lastrowid

    def remover_site(self, site_id: int) -> bool:
        with self._conexao:
            cursor = self._conexao.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        return cursor.rowcount > 0

    def listar_sites(self) -> list[Site]:
        linhas = self._conexao.execute("SELECT * FROM sites ORDER BY id").fetchall()
        return [self._site(l) for l in linhas]

    def buscar_site(self, site_id: int) -> Site | None:
        linha = self._conexao.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        return self._site(linha) if linha else None

    # --- checagens ---

    def registrar(self, site_id: int, resultado: Resultado, quando: datetime | None = None):
        with self._conexao:
            self._conexao.execute(
                "INSERT INTO checagens (site_id, verificado_em, ok, status, tempo_ms, erro) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (site_id, _texto_da_data(quando or agora_utc()), int(resultado.ok),
                 resultado.status, resultado.tempo_ms, resultado.erro),
            )

    def historico(self, site_id: int, limite: int = 20) -> list[Checagem]:
        linhas = self._conexao.execute(
            "SELECT * FROM checagens WHERE site_id = ? ORDER BY verificado_em DESC, id DESC LIMIT ?",
            (site_id, limite),
        ).fetchall()
        return [Checagem(l["verificado_em"], bool(l["ok"]), l["status"], l["tempo_ms"], l["erro"])
                for l in linhas]

    def resumo(self, horas: float = 24, agora: datetime | None = None) -> list[ResumoSite]:
        desde = _texto_da_data((agora or agora_utc()) - timedelta(hours=horas))
        resumos = []
        for site in self.listar_sites():
            linhas = self._conexao.execute(
                "SELECT verificado_em, ok, tempo_ms, erro FROM checagens "
                "WHERE site_id = ? AND verificado_em >= ? ORDER BY verificado_em, id",
                (site.id, desde),
            ).fetchall()

            total = len(linhas)
            ok = sum(l["ok"] for l in linhas)
            # tempo só conta quando o servidor respondeu (timeout e recusa não têm tempo)
            tempos = [l["tempo_ms"] for l in linhas if l["tempo_ms"] is not None]
            falhas = [l for l in linhas if not l["ok"]]

            resumos.append(ResumoSite(
                site=site,
                total=total,
                ok=ok,
                uptime_pct=round(100 * ok / total, 2) if total else None,
                tempo_medio_ms=round(sum(tempos) / len(tempos)) if tempos else None,
                p95_ms=percentil(tempos, 95),
                ultima_falha=falhas[-1]["verificado_em"] if falhas else None,
                ultimo_erro=falhas[-1]["erro"] if falhas else None,
            ))
        return resumos
