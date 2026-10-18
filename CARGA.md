# Teste de carga

Pergunta: o motor aguenta volume sem deixar Pix sem resposta?

## Como foi medido

- Pacote em `benchmark_antifraude/`: sobe um ambiente Docker exclusivo com o código atual, insere **100 mil Pix históricos** direto no Postgres (transação + análise + regras disparadas, como o motor gravaria) e dispara Pix novos **pela API**, em taxa fixa, por 30 s em cada patamar.
- Três perfis:
  - **distribuído**: até 10 mil pagadores e destinos diferentes;
  - **mesmo destino**: muitos pagadores pagando a mesma conta (a loja);
  - **mesmo pagador**: um único CPF/CNPJ pagando vários destinos.
- Máquina: notebook com Docker Desktop (12 CPUs, 8 GB), com gerador de carga, API e banco **dividindo a mesma máquina**. Os números servem para comparar versões e achar gargalos. Não são capacidade de produção.
- Timeout do cliente: 5 s. "Erro" = HTTP diferente de 201 ou timeout. `rejected` e `two_factor_required` são decisões, não erros.

## O que o teste encontrou e o que mudou

**1. Um processo só.** A API subia com um único processo Python, e o distribuído estabilizava em ~55 Pix/s. → Dockerfile com **4 processos** (`WEB_WORKERS`).

**2. A trava do destino colocava a loja inteira em fila.** Toda análise para a mesma conta esperava a anterior. Uma conta com ~7 mil Pix de histórico leva ~100 ms por análise, então cabiam ~10 Pix/s por conta; a 25 Pix/s, 76% dos pagamentos estouravam o tempo. A trava existia só para a TX02/TX03 contarem pagadores com exatidão em chegadas simultâneas, uma exatidão que não muda nenhuma decisão. → **O destino deixou de ser travado.** A trava do **pagador** ficou: ela protege a rajada e a soma do dia.

**3. Quem passava do limite da fila do pagador recebia timeout, ou seja, nenhuma decisão.** → **TX09**: quem espera mais de **0,5 s** na fila do mesmo pagador é analisado mesmo assim e leva **piso de 2FA**. O limite começou em 2 s; o teste mostrou que esperas longas seguravam conexões do banco e os Pix seguintes esperavam *antes* da fila. Com 0,5 s, cada espera devolve a conexão rápido.

## Resultados

p95 = tempo que 95% das respostas não ultrapassam, medido pelo cliente.

### Distribuído (contas diferentes)

| Carga | Antes (1 processo, trava no destino) | Depois (4 processos, trava só no pagador) |
|---|---|---|
| 50 Pix/s | p95 478 ms | **p95 55 ms**, 0 erros |
| 100 Pix/s | só 55/s atendidos, p95 2,5 s | **p95 59 ms**, 0 erros |
| 200 Pix/s | só 55/s atendidos, p95 2,6 s | 155/s atendidos, p95 0,9 s, 0 erros |

### Mesmo destino (a loja)

| Carga | Antes | Depois |
|---|---|---|
| 10 Pix/s | p95 122 ms | p95 127 ms |
| 25 Pix/s | **76% de timeouts** | **p95 159 ms**, 0 erros |
| 50 Pix/s | — | **p95 220 ms**, 0 erros |
| 100 Pix/s | — | 61/s atendidos, p95 2,5 s, 0,05% de erros (saturação da máquina) |

### Mesmo pagador (um único CPF/CNPJ)

| Carga | Sem TX09 | TX09 com 2 s | TX09 com 0,5 s (final) |
|---|---|---|---|
| 25 Pix/s | p95 5 s, **24% de timeouts** | p95 78 ms, 0 erros | **p95 74 ms**, 0 erros |
| 50 Pix/s | — | 21% de timeouts | **p95 0,9 s, 0 erros** |
| 100 Pix/s | — | — | 67/s atendidos, p95 3,3 s, 0,24% de erros |

## Limites conhecidos

- **Pagamento em lote** (folha, repasse a vendedores) passa pela fila do mesmo pagador: acima de ~25 Pix/s, os excedentes pedem 2FA (TX09). Em produção, lote é outro produto: aprovação do lote inteiro com um único 2FA e envio em ritmo controlado. Fica fora do escopo deste motor, que analisa um Pix por vez.
- **Contagem aproximada na TX02/TX03** em chegadas simultâneas para a mesma conta: pode ver um ou dois pagadores a menos numa janela de uma hora. Troca aceita para não serializar a loja.
- **Ambiente**: gerador, API e banco na mesma máquina. Acima de ~150 Pix/s o teto observado é do notebook. Uma medição séria de capacidade precisa do gerador em outra máquina.
- **Instrumentação**: a coleta de CPU/memória dos containers falhou no Docker Desktop; as conclusões vêm de latência, erros e das estatísticas do Postgres (`pg_stat_statements`, esperas e travas).
- **Dados sintéticos**: o histórico serve ao volume, não mede detecção de fraude. A qualidade das decisões está em `CALIBRACAO.md`.

## Como repetir

```powershell
docker compose up -d --build
python .\benchmark_antifraude\rodar.py --linhas 100000 --perfis distribuido
python .\benchmark_antifraude\rodar.py --linhas 100000 --perfis mesmo_destino
python .\benchmark_antifraude\rodar.py --linhas 100000 --perfis mesmo_pagador --taxas 10,25,50,100
```

Cada execução cria um banco novo e grava `RELATORIO_CARGA.txt` em `benchmark_antifraude/resultados/<execução>/`.
