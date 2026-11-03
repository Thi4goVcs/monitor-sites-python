from datetime import datetime, timedelta, timezone

import pytest

from monitor.banco import Banco, SiteJaExiste, percentil
from monitor.verificador import Resultado

AGORA = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

OK = lambda ms=100: Resultado(True, 200, ms, None)
FALHA = Resultado(False, 500, 50, "HTTP 500")
TIMEOUT = Resultado(False, None, None, "timeout")


def test_adicionar_e_listar(banco):
    a = banco.adicionar_site("A", "http://a.com")
    b = banco.adicionar_site("B", "http://b.com", esperado=401, contem="oi")
    sites = banco.listar_sites()
    assert [s.id for s in sites] == [a, b]
    assert sites[1].esperado == 401
    assert sites[1].contem == "oi"
    assert sites[0].esperado is None


def test_url_repetida_e_recusada(banco):
    banco.adicionar_site("A", "http://a.com")
    with pytest.raises(SiteJaExiste):
        banco.adicionar_site("Outro nome", "http://a.com")
    assert len(banco.listar_sites()) == 1


def test_remover_apaga_o_site_e_o_historico(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, OK())
    assert banco.remover_site(site_id)
    assert banco.listar_sites() == []
    # o histórico some junto (ON DELETE CASCADE, que só funciona com a PRAGMA ligada)
    sobrou = banco._conexao.execute("SELECT COUNT(*) FROM checagens").fetchone()[0]
    assert sobrou == 0


def test_remover_site_inexistente(banco):
    assert not banco.remover_site(999)


def test_dados_persistem_entre_conexoes(tmp_path):
    caminho = str(tmp_path / "x.db")
    with Banco(caminho) as b:
        site_id = b.adicionar_site("A", "http://a.com")
        b.registrar(site_id, OK())
    with Banco(caminho) as b:
        assert len(b.listar_sites()) == 1
        assert len(b.historico(site_id)) == 1


def test_uptime_e_contagens(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    for _ in range(3):
        banco.registrar(site_id, OK(), AGORA - timedelta(minutes=5))
    banco.registrar(site_id, FALHA, AGORA - timedelta(minutes=2))

    (r,) = banco.resumo(24, AGORA)
    assert r.total == 4
    assert r.ok == 3
    assert r.uptime_pct == 75.0


def test_uptime_arredonda_em_duas_casas(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, OK(), AGORA - timedelta(minutes=3))
    banco.registrar(site_id, OK(), AGORA - timedelta(minutes=2))
    banco.registrar(site_id, FALHA, AGORA - timedelta(minutes=1))
    assert banco.resumo(24, AGORA)[0].uptime_pct == 66.67


def test_site_sem_checagens_nao_tem_uptime(banco):
    banco.adicionar_site("A", "http://a.com")
    (r,) = banco.resumo(24, AGORA)
    assert r.total == 0
    assert r.uptime_pct is None
    assert r.tempo_medio_ms is None
    assert r.p95_ms is None


def test_janela_de_horas_ignora_checagens_antigas(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, FALHA, AGORA - timedelta(hours=30))
    banco.registrar(site_id, OK(), AGORA - timedelta(hours=1))
    assert banco.resumo(24, AGORA)[0].uptime_pct == 100.0
    assert banco.resumo(48, AGORA)[0].uptime_pct == 50.0


def test_tempo_medio_ignora_checagens_sem_resposta(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, OK(100), AGORA - timedelta(minutes=3))
    banco.registrar(site_id, OK(300), AGORA - timedelta(minutes=2))
    # o timeout não tem tempo: se entrasse como 0, a média cairia pra 133
    banco.registrar(site_id, TIMEOUT, AGORA - timedelta(minutes=1))
    (r,) = banco.resumo(24, AGORA)
    assert r.tempo_medio_ms == 200
    assert r.total == 3


def test_ultima_falha_e_o_erro_dela(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, FALHA, AGORA - timedelta(hours=3))
    banco.registrar(site_id, TIMEOUT, AGORA - timedelta(hours=2))
    banco.registrar(site_id, OK(), AGORA - timedelta(hours=1))
    (r,) = banco.resumo(24, AGORA)
    assert r.ultimo_erro == "timeout"
    assert r.ultima_falha.startswith("2026-01-15T10:00:00")


def test_sem_falha_nao_tem_ultima_falha(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, OK(), AGORA - timedelta(minutes=1))
    assert banco.resumo(24, AGORA)[0].ultima_falha is None


def test_resumo_separa_os_sites(banco):
    a = banco.adicionar_site("A", "http://a.com")
    b = banco.adicionar_site("B", "http://b.com")
    banco.registrar(a, OK(), AGORA - timedelta(minutes=1))
    banco.registrar(b, FALHA, AGORA - timedelta(minutes=1))
    resumos = {r.site.nome: r for r in banco.resumo(24, AGORA)}
    assert resumos["A"].uptime_pct == 100.0
    assert resumos["B"].uptime_pct == 0.0


def test_historico_vem_do_mais_recente_pro_mais_antigo_e_respeita_o_limite(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    for minutos in (30, 20, 10):
        banco.registrar(site_id, OK(minutos), AGORA - timedelta(minutes=minutos))
    historico = banco.historico(site_id, limite=2)
    assert [c.tempo_ms for c in historico] == [10, 20]


def test_historico_guarda_erro_e_status(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    banco.registrar(site_id, FALHA)
    (c,) = banco.historico(site_id)
    assert (c.ok, c.status, c.erro) == (False, 500, "HTTP 500")


def test_datas_em_fusos_diferentes_viram_utc(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    fuso = timezone(timedelta(hours=-3))
    banco.registrar(site_id, OK(), datetime(2026, 1, 15, 9, 0, 0, tzinfo=fuso))
    assert banco.historico(site_id)[0].verificado_em == "2026-01-15T12:00:00+00:00"


# --- percentil ---

def test_percentil_posto_mais_proximo():
    valores = list(range(1, 101))
    assert percentil(valores, 95) == 95
    assert percentil(valores, 50) == 50
    assert percentil(valores, 100) == 100


def test_percentil_nao_depende_da_ordem_de_entrada():
    assert percentil([300, 100, 200], 100) == 300


def test_percentil_de_um_valor_e_de_lista_vazia():
    assert percentil([42], 95) == 42
    assert percentil([], 95) is None


def test_p95_mostra_a_lentidao_que_a_media_dilui(banco):
    site_id = banco.adicionar_site("A", "http://a.com")
    # 18 respostas de 100 ms e 2 lentas: em 20 amostras o p95 é o posto 19, que já é lento
    for i in range(18):
        banco.registrar(site_id, OK(100), AGORA - timedelta(minutes=30 - i))
    banco.registrar(site_id, OK(5000), AGORA - timedelta(minutes=5))
    banco.registrar(site_id, OK(6000), AGORA - timedelta(minutes=4))
    (r,) = banco.resumo(24, AGORA)
    assert r.p95_ms == 5000
    assert r.tempo_medio_ms == 640
