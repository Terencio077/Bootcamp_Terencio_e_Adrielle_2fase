# Carga e desempenho do motor antifraude Pix

Este pacote cria um ambiente Docker exclusivo, usa o codigo atual do seu projeto,
insere historico sintetico e mede novas requisicoes concorrentes na API real.
Nao modifica o codigo do motor. Nao acessa o banco do compose original.

## Preparacao no Windows

Requisitos: Python 3.10 ou superior, Docker Desktop iniciado, Docker Compose v2,
acesso a internet para baixar imagens e dependencias, memoria e disco disponiveis.
Nenhum `pip install` no computador e necessario.

Extraia a pasta `benchmark_antifraude` na raiz do projeto:

```text
Bootcamp_Terencio_e_Adrielle_2fase-main/
    services/
    docker-compose.yml
    benchmark_antifraude/
        rodar.py
        compose.benchmark.yml
        seed.sql
        monitoring.sql
```

No PowerShell, dentro da raiz do projeto, comece pelo teste curto:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 1000 --taxas 2,5 --segundos 10 --perfis distribuido
```

Depois rode a primeira bateria:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 100000
```

O padrao oferece 10, 25, 50, 100 e 200 requisicoes/s, por 30 segundos cada,
em tres perfis. Sao aproximadamente 7min30 de janelas de carga, mais build,
seed, aquecimento, drenagem das chamadas pendentes e monitoramento.
E uma busca exploratoria de gargalos. Nao basta para declarar capacidade de producao.

Leia o relatorio antes de aumentar. Para comparar crescimento do historico:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 500000
python .\benchmark_antifraude\rodar.py --linhas 1000000
```

Cada invocacao cria um banco novo, com nome exclusivo. O seed se recusa a rodar
se houver Pix na tabela; nao limpa tabelas existentes. O banco nao expoe porta
no host e a API usa `127.0.0.1:18005`. Se essa porta estiver ocupada, use
`--porta 18006`. Containers do teste param ao final, preservando o volume.
O relatorio mostra o comando especifico para remover SOMENTE esse ambiente e volume.
Remova os ambientes anteriores depois de inspecionar: varias bases grandes consomem disco.
Para manter a API e banco ligados apos a execucao, use `--manter-ligado`.

## O que esta sendo exercitado

| Perfil | Distribuicao | Pergunta |
| --- | --- | --- |
| distribuido | Ate 10 mil pagadores e destinos | Como a API atende contas distintas? |
| mesmo_destino | Muitos pagadores para uma conta | Quanto custa a disputa pela trava do destino? |
| mesmo_pagador | Um pagador para varios destinos | Quanto custa a disputa pela trava do pagador? |

Os perfis rodam nessa ordem e acumulam novas transacoes no mesmo banco. Os patamares
sao constantes, sem rampa; cada um aguarda a conclusao das chamadas antes do seguinte.
Isso permite observar tambem o custo da transicao e a drenagem. Para comparacoes
mais controladas, execute um perfil por invocacao, com banco novo:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 100000 --perfis mesmo_destino --taxas 10,25,50 --segundos 60
```

O historico ocupa ate 90 dias, inclui janelas recentes e concentracao em algumas
contas; mistura PF/PJ, contas novas/antigas, aprovados, 2FA e recusados com rule_hits.
O total de linhas do banco e maior que o numero de Pix: cada Pix tem analise e
parte deles tem regras associadas. As insercoes usam SQL no banco, mantendo os
indices, e executam ANALYZE antes da carga. Nao ha criacao de milhoes de Pix por HTTP.

As analises historicas sao fixtures sinteticas identificadas por `bench-fixture`.
Nao foram calculadas pelo motor, nao simulam toda a distribuicao real de fraude
e nao validam a calibracao. Todas as novas requisicoes de carga passam pela API.
Os documentos sao identificadores sinteticos no formato aceito pelo projeto;
nao sao uma base de CPFs/CNPJs reais ou com verificacao cadastral.

As datas das novas requisicoes seguem uma referencia de 14h no fuso de Sao Paulo,
avancando com o tempo real desde o inicio da bateria. Isso mantem o historico
visivel e reduz mudancas de comportamento por horario noturno. IDs novos evitam
medir apenas o caminho rapido de idempotencia. Valores e dispositivos variam;
nao ha expectativa de todos os Pix serem aprovados.

## Como interpretar o relatorio

Envie `RELATORIO_CARGA.txt`, criado em `benchmark_antifraude/resultados/<execucao>/`.
`resultado.json` guarda dados adicionais, hashes do codigo e commit quando disponivel.
Os CSVs permitem recalcular percentis e observar erros individuais.

- **Ofertada:** taxa programada. **Iniciadas:** chamadas que realmente comecaram na janela.
- **Concluidas na janela:** respostas recebidas dentro dos segundos programados.
  A vazao incluindo drenagem tambem fica no JSON. Chamadas lentas podem concluir depois.
- **Nao enviadas:** o gerador atrasou ou atingiu o limite de chamadas em voo.
  Nao classifique automaticamente isso como falha HTTP ou limite do motor.
- **p95/p99 HTTP:** tempo ate ler a resposta inteira, incluindo rede local, API,
  travas, banco e persistencia. Percentis incluem respostas de erro; confira a taxa de erros junto.
- **decision_ms:** janela medida pela propria API. Nao equivale a tempo puro das regras.
- **Erros tecnicos:** HTTP diferente de 201, timeout, conexao ou resposta invalida.
  `approved`, `rejected` e `two_factor_required` sao decisoes de negocio.
- **Fallbacks:** regras `FAILSAFE_*`, sinalizadas separadamente mesmo com HTTP 201.

Metas iniciais: p95 <= 1000ms e erros <= 2%, com carga alvo sustentada e sem fallback.
Sao metas experimentais editaveis (`--p95-ms` e `--erro-pct`), nao exigencias regulatorias.
Com poucas amostras, p99 e instavel. Nao use um patamar de poucos segundos para
afirmar SLA. Repita os patamares relevantes e depois rode uma carga sustentada:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 100000 --perfis distribuido --taxas 50 --segundos 300
```

O gerador usa conexoes HTTP persistentes por thread, taxa de chegada independente
das respostas, sem retry e sem fila ilimitada. Atrasos nao sao compensados por rajadas.
Padrao: ate 100 chamadas simultaneas e timeout de 5s. Para experimentar mais:

```powershell
python .\benchmark_antifraude\rodar.py --linhas 100000 --taxas 50,100,200,500 --concorrencia 200
```

Se mais de 20% das chamadas de um patamar tiverem erro tecnico ou fallback,
os patamares seguintes daquele perfil sao pulados e os outros perfis continuam.
Isso fica registrado no JSON e relatorio. Um processo concluido sem erro nao
significa que as metas de desempenho foram atendidas: leia cada patamar.

## Banco e recursos

O pacote habilita `pg_stat_statements`, reseta suas estatisticas antes de cada
perfil e registra consultas com maior tempo acumulado, media, maximo e blocos lidos.
Tambem amostra sessoes, eventos de espera, bloqueios, CPU/memoria/I/O dos containers
a cada aproximadamente 5s. Os logs finais de cada perfil sao preservados.
Essa instrumentacao tambem consome recursos e pode nao captar bloqueios curtos.

Nao ha medicao direta de espera pelo pool SQLAlchemy, CPU puro de cada regra ou
CPU/memoria do gerador. Conexoes e esperas do banco ajudam a levantar hipoteses,
mas nao provam que o pool e o gargalo. Gerador, Docker e banco dividem a maquina.
Antes de atribuir um teto ao motor, confira nao enviadas, atraso de agendamento,
CPU do host e limites de recursos do Docker Desktop. Um segundo computador para
o gerador seria uma etapa posterior de verificacao.

O codigo atual e construido pelo Dockerfile original, sem alterar numero de workers,
pool, regras ou logs. A imagem do Postgres e fixada na versao principal 16; o ID
efetivamente utilizado fica no resultado. Dependencias nao fixadas do projeto
podem mudar entre builds; registre o ambiente ao comparar execucoes.

## Validacao do pacote

Consulte `VALIDACAO.txt` para saber exatamente o que foi verificado antes da entrega.
O teste curto e obrigatorio para validar a integracao no seu Docker e esquema atuais.

Referencias tecnicas:
- https://www.postgresql.org/docs/16/pgstatstatements.html
- https://www.postgresql.org/docs/16/monitoring-stats.html
- https://docs.python.org/3/library/concurrent.futures.html
