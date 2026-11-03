# monitor-sites-python

Monitor de sites de linha de comando. Você cadastra os endereços, ele checa todos de uma vez, guarda cada resultado num SQLite e depois mostra o uptime e o tempo de resposta de cada um. Python puro: só biblioteca padrão (`urllib`, `sqlite3`, `argparse`, `concurrent.futures`), o único pacote externo é o `pytest` pros testes.

Primeiro projeto de automação do portfólio. A ideia era uma ferramenta que dá pra colocar no agendador do sistema (`cron`, Agendador de Tarefas) e esquecer, então ela sai com código 1 quando algum site cai.

## Usando

```bash
python -m monitor adicionar https://github.com --nome GitHub
python -m monitor adicionar https://meusite.com/api/saude --contem '"status":"ok"'
python -m monitor adicionar https://meusite.com/admin --esperado 401

python -m monitor listar
python -m monitor checar                      # checa todos agora
python -m monitor checar --repetir 60         # de novo a cada 60 s (Ctrl+C para)
python -m monitor resumo --horas 24           # uptime, média e p95 por site
python -m monitor historico 2                 # últimas checagens do site 2
python -m monitor remover 2
```

Os dados ficam em `monitor.db` na pasta onde você rodou (`--banco` troca o arquivo).

Uma rodada de `checar` de verdade, com 5 sites que eu cadastrei de propósito pra ver cada tipo de falha:

```
[09:43:18] OK      200    279 ms  GitHub
[09:43:18] FALHOU  -         -  cert vencido: erro de SSL: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired
[09:43:18] FALHOU  -         -  dns quebrado: DNS: não achei o endereço
[09:43:18] FALHOU  404    349 ms  404: HTTP 404
```

(O `example.com` também falhou nessa rodada, mas por outro motivo, explicado nos limites.)

## O que conta como "no ar"

Por padrão, resposta 2xx ou 3xx. Redirecionamento é seguido, então vale o status final. Dois ajustes por site:

- `--esperado 401`: o status que significa "tudo certo". Serve pra endpoint que exige login e responde 401 quando está saudável.
- `--contem "texto"`: o texto precisa aparecer na página. Pega o caso clássico de o site cair mas a página de erro voltar com status 200.

Quando falha, o motivo aparece escrito: `HTTP 5xx`/`4xx`, `timeout`, `conexão recusada`, `DNS: não achei o endereço`, `erro de SSL`, o texto que não apareceu, ou (pra qualquer outro problema de rede) `falha de rede` com a mensagem do sistema.

## Testes

```bash
pip install pytest
pytest
```

64 testes. Em vez de bater em site de verdade (o que quebra quando a internet cai), os testes sobem um servidor HTTP local numa thread, com um endereço pra cada comportamento: 200, 500, 404, 401, redirecionamento, laço de redirecionamento, resposta lenta, resposta que nunca chega, página gigante e página que devolve erro com status 200. Ainda assim, tem teste que depende de a rede se comportar normalmente, como o DNS de um domínio `.invalid` (reservado pela RFC 2606, nunca resolve).

Cobrem: todos os tipos de falha, o `--esperado` e o `--contem`, as contas de uptime e percentil (com datas controladas, sem depender do relógio), a janela de horas, o histórico, o `ON DELETE CASCADE`, os códigos de saída e uma checagem de que 4 sites lentos em paralelo levam o tempo de um e não de quatro.

Além dos testes, rodei contra sites reais (GitHub, um certificado vencido de propósito em `expired.badssl.com`, um domínio inexistente, uma página 404) pra ver as mensagens de verdade.

## Decisões que valem comentar

**Só `http://` e `https://`.** O `urllib` abre `file:///...` e `ftp://` sem reclamar. Numa ferramenta que recebe endereço de fora, deixar passar `file:///etc/passwd` seria ler arquivo da máquina em vez de monitorar site. A URL é validada ao cadastrar e de novo na hora de checar.

**As requisições rodam em paralelo, a escrita no banco não.** O `ThreadPoolExecutor` faz as checagens ao mesmo tempo, então uma rodada leva o tempo do site mais lento e não a soma. Os resultados voltam pra thread principal, que grava tudo. Assim nenhuma conexão do SQLite é usada por uma thread diferente da que a criou.

**Timeout não tem tempo de resposta.** Se o site não respondeu, não existe "quanto demorou". Guardo `NULL` em vez de 0 ou do valor do timeout, porque um 0 puxaria a média pra baixo (um site caindo pareceria mais rápido). Tem teste pra isso.

**p95 além da média.** A média esconde lentidão: com 18 respostas de 100 ms e 2 de 5 a 6 segundos, a média é 640 ms e parece aceitável, mas o p95 mostra 5000 ms. Uso o método do posto mais próximo (o menor valor que cobre 95% das amostras).

**Datas em UTC, sempre no mesmo formato.** Dá pra comparar como texto no SQL e a ordem sai certa. Na tela convertem pro horário local.

**`PRAGMA foreign_keys = ON`.** O SQLite ignora chave estrangeira por padrão. Sem essa linha, o `ON DELETE CASCADE` não roda e remover um site deixa o histórico dele órfão no banco.

## Limites que conheço

- **Erro de SSL pode ser da minha máquina, não do site.** O `example.com` falhou aqui com `unable to get local issuer certificate`, mesmo abrindo normalmente no navegador. O Python verifica o certificado contra o repositório de certificados do sistema e não busca intermediário que falte na cadeia, coisa que o navegador faz. Se aparecer erro de SSL num site que abre no browser, desconfie disso. Não coloquei uma opção "ignorar certificado" de propósito.
- O `--timeout` vale pra cada operação de rede, não pro tempo total: um servidor que manda um byte a cada segundo nunca estoura.
- Só lê os primeiros 256 KB da resposta (pro `--contem`), então um texto que só aparece depois disso não é encontrado.
- No Windows, com `--timeout 2` uma conexão recusada em `localhost` apareceu como `timeout` e não como "conexão recusada" (com mais tempo aparece certo). Os testes usam um timeout maior por causa disso.
- Sem alerta (e-mail, Slack): só a saída com código 1 e o histórico. Quem quiser avisar precisa envolver o comando num script.
- Checagem é um `GET` simples, sem cabeçalho de autenticação, sem POST e sem corpo.
- O banco cresce sem limite: não tem limpeza de checagens antigas.
