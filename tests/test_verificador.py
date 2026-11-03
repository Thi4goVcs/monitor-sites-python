import pytest

from monitor.verificador import checar, validar_url


def test_site_no_ar(servidor):
    r = checar(servidor + "/ok")
    assert r.ok
    assert r.status == 200
    assert r.erro is None
    assert r.tempo_ms is not None and r.tempo_ms >= 0


def test_status_500_e_falha_com_status_e_tempo_registrados(servidor):
    r = checar(servidor + "/erro")
    assert not r.ok
    assert r.status == 500
    assert r.erro == "HTTP 500"
    assert r.tempo_ms is not None


def test_status_404_e_falha(servidor):
    r = checar(servidor + "/naoexiste")
    assert not r.ok
    assert r.status == 404


def test_redirecionamento_e_seguido(servidor):
    r = checar(servidor + "/redireciona")
    assert r.ok
    assert r.status == 200


def test_laco_de_redirecionamento_e_falha_e_nao_trava(servidor):
    r = checar(servidor + "/laco")
    assert not r.ok


def test_status_esperado_diferente_de_2xx(servidor):
    # um endpoint que responde 401 sem login está "no ar" se é isso que se espera dele
    assert checar(servidor + "/privado", esperado=401).ok
    assert not checar(servidor + "/privado").ok


def test_status_esperado_nao_bate(servidor):
    r = checar(servidor + "/ok", esperado=204)
    assert not r.ok
    assert r.status == 200
    assert "esperava 204" in r.erro


def test_esperado_404_numa_pagina_que_existe_e_falha(servidor):
    assert not checar(servidor + "/ok", esperado=404).ok


def test_contem_texto_presente(servidor):
    assert checar(servidor + "/pagina", contem="Bem-vindo").ok


def test_contem_texto_ausente_mesmo_com_200(servidor):
    r = checar(servidor + "/erro-com-200", contem="Bem-vindo")
    assert not r.ok
    assert r.status == 200
    assert "não apareceu" in r.erro


def test_contem_com_acentos(servidor):
    assert checar(servidor + "/acentos", contem="ação").ok


def test_contem_so_olha_os_primeiros_256kb(servidor):
    # o "FIM" está além do limite de leitura: a checagem não baixa a página inteira
    assert not checar(servidor + "/enorme", contem="FIM").ok


def test_timeout(servidor):
    r = checar(servidor + "/travado", timeout=0.3)
    assert not r.ok
    assert r.status is None
    assert r.tempo_ms is None
    assert r.erro == "timeout"


def test_tempo_de_resposta_reflete_a_lentidao_do_servidor(servidor):
    r = checar(servidor + "/lento")
    assert r.ok
    assert 500 <= r.tempo_ms < 2500


def test_conexao_recusada(porta_fechada):
    r = checar(porta_fechada)
    assert not r.ok
    assert r.status is None
    assert "recusada" in r.erro


def test_dns_que_nao_resolve():
    # .invalid é reservado pela RFC 2606: nunca resolve
    r = checar("http://site-que-nao-existe.invalid/", timeout=5)
    assert not r.ok
    assert r.status is None
    assert r.erro


def test_https_apontando_pra_servidor_http_e_erro_de_ssl(servidor):
    r = checar(servidor.replace("http://", "https://") + "/ok", timeout=5)
    assert not r.ok
    assert "SSL" in r.erro


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://exemplo.com/arquivo",
    "javascript:alert(1)",
    "exemplo.com",
    "http://",
    "",
])
def test_so_aceita_http_e_https_com_endereco(url):
    with pytest.raises(ValueError):
        validar_url(url)


def test_checar_tambem_recusa_esquema_perigoso():
    with pytest.raises(ValueError):
        checar("file:///etc/passwd")


@pytest.mark.parametrize("url", ["http://exemplo.com", "https://exemplo.com/a?b=1", "http://localhost:8080/x"])
def test_urls_validas_passam(url):
    assert validar_url(url) == url
