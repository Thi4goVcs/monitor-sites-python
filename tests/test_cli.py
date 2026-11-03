from monitor.cli import main


def rodar(capsys, tmp_path, *args):
    codigo = main(["--banco", str(tmp_path / "cli.db"), *args])
    saida = capsys.readouterr()
    return codigo, saida.out, saida.err


def test_adicionar_e_listar(capsys, tmp_path, servidor):
    codigo, out, _ = rodar(capsys, tmp_path, "adicionar", servidor + "/ok", "--nome", "Meu site")
    assert codigo == 0
    assert "Meu site" in out

    codigo, out, _ = rodar(capsys, tmp_path, "listar")
    assert codigo == 0
    assert "Meu site" in out
    assert servidor + "/ok" in out


def test_nome_padrao_e_o_endereco(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    _, out, _ = rodar(capsys, tmp_path, "listar")
    assert servidor.replace("http://", "") in out


def test_url_invalida_e_recusada(capsys, tmp_path):
    codigo, _, err = rodar(capsys, tmp_path, "adicionar", "file:///etc/passwd")
    assert codigo == 2
    assert "URL inválida" in err
    _, out, _ = rodar(capsys, tmp_path, "listar")
    assert "Nenhum site" in out


def test_url_repetida_e_recusada(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    codigo, _, err = rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    assert codigo == 2
    assert "já está cadastrado" in err


def test_checar_sem_sites_cadastrados(capsys, tmp_path):
    codigo, _, err = rodar(capsys, tmp_path, "checar")
    assert codigo == 2
    assert "Nenhum site" in err


def test_checar_tudo_no_ar_sai_com_0(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok", "--nome", "A")
    rodar(capsys, tmp_path, "adicionar", servidor + "/pagina", "--nome", "B")
    codigo, out, _ = rodar(capsys, tmp_path, "checar")
    assert codigo == 0
    assert out.count("OK") == 2
    assert "FALHOU" not in out


def test_checar_com_um_site_fora_sai_com_1_mas_checa_todos(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok", "--nome", "bom")
    rodar(capsys, tmp_path, "adicionar", servidor + "/erro", "--nome", "ruim")
    codigo, out, _ = rodar(capsys, tmp_path, "checar")
    assert codigo == 1
    assert "OK" in out and "bom" in out
    assert "FALHOU" in out and "ruim" in out and "HTTP 500" in out


def test_checar_respeita_o_status_esperado_e_o_texto_exigido(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/privado", "--esperado", "401", "--nome", "login")
    rodar(capsys, tmp_path, "adicionar", servidor + "/erro-com-200", "--contem", "Bem-vindo", "--nome", "falso-ok")
    codigo, out, _ = rodar(capsys, tmp_path, "checar")
    assert codigo == 1
    linhas = out.splitlines()
    login = next(l for l in linhas if "login" in l)
    falso = next(l for l in linhas if "falso-ok" in l)
    assert "OK" in login
    assert "FALHOU" in falso
    assert "não apareceu" in out


def test_checar_servidor_fora_do_ar(capsys, tmp_path, porta_fechada):
    rodar(capsys, tmp_path, "adicionar", porta_fechada, "--nome", "morto")
    codigo, out, _ = rodar(capsys, tmp_path, "checar", "--timeout", "6")
    assert codigo == 1
    assert "recusada" in out


def test_checar_em_paralelo_leva_o_tempo_do_mais_lento_nao_a_soma(capsys, tmp_path, servidor):
    import time
    for i in range(4):
        rodar(capsys, tmp_path, "adicionar", servidor + "/lento?x=" + str(i), "--nome", f"s{i}")
    inicio = time.perf_counter()
    codigo, out, _ = rodar(capsys, tmp_path, "checar", "--paralelo", "4")
    total = time.perf_counter() - inicio
    assert codigo == 0
    # 4 sites de 0,6 s: em sequência seriam 2,4 s
    assert total < 1.8


def test_repetir_faz_varias_rodadas_e_acumula_historico(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok", "--nome", "A")
    codigo, out, _ = rodar(capsys, tmp_path, "checar", "--repetir", "0.05", "--vezes", "3")
    assert codigo == 0
    assert out.count("OK") == 3
    _, out, _ = rodar(capsys, tmp_path, "resumo")
    assert "3/3" in out
    assert "100.00%" in out


def test_resumo_depois_de_checagens_com_falha(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok", "--nome", "bom")
    rodar(capsys, tmp_path, "adicionar", servidor + "/erro", "--nome", "ruim")
    rodar(capsys, tmp_path, "checar")
    rodar(capsys, tmp_path, "checar")
    codigo, out, _ = rodar(capsys, tmp_path, "resumo")
    assert codigo == 0
    assert "100.00%" in out
    assert "0.00%" in out
    assert "Última falha" in out
    assert "HTTP 500" in out


def test_resumo_sem_checagens(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    _, out, _ = rodar(capsys, tmp_path, "resumo")
    assert "sem dados" in out


def test_historico(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/erro", "--nome", "ruim")
    rodar(capsys, tmp_path, "checar")
    codigo, out, _ = rodar(capsys, tmp_path, "historico", "1")
    assert codigo == 0
    assert "FALHOU" in out
    assert "HTTP 500" in out


def test_historico_de_site_inexistente(capsys, tmp_path):
    codigo, _, err = rodar(capsys, tmp_path, "historico", "99")
    assert codigo == 2
    assert "não existe" in err


def test_remover(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    codigo, _, _ = rodar(capsys, tmp_path, "remover", "1")
    assert codigo == 0
    _, out, _ = rodar(capsys, tmp_path, "listar")
    assert "Nenhum site" in out
    codigo, _, err = rodar(capsys, tmp_path, "remover", "1")
    assert codigo == 2


def test_paralelo_zero_e_recusado(capsys, tmp_path, servidor):
    rodar(capsys, tmp_path, "adicionar", servidor + "/ok")
    codigo, _, err = rodar(capsys, tmp_path, "checar", "--paralelo", "0")
    assert codigo == 2
