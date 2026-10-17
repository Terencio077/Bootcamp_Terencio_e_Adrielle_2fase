# [Nome do grupo]

**Integrantes:** [nomes]

Motor antifraude de Pix: uma API que recebe um Pix, olha o histórico de quem paga e de quem recebe, aplica as regras e devolve `approved`, `two_factor_required` ou `rejected`, com o motivo de cada decisão gravado e consultável.

## Como o motor de decisão funciona

### Duas perguntas, dois eixos

A apresentação da QI Tech fez duas perguntas diferentes: **"quem é essa pessoa?"** e **"essa transação é legítima?"**. O motor responde cada uma num eixo próprio, com uma nota de 0 a 100+:

| Eixo | Pergunta | Exemplos de sinal |
|---|---|---|
| **Identidade** | É mesmo o dono da conta? | aparelho nunca usado, viagem impossível, rajada de Pix |
| **Transação** | Mesmo sendo ele, o Pix é legítimo? | conta de destino recém-aberta, conta laranja, valor fora do perfil |

A separação existe porque **as três decisões não resolvem as duas dúvidas do mesmo jeito**. O 2FA prova *quem* está pagando. Ele não prova que o Pix é legítimo. No golpe do falso parente, no falso funcionário do banco ou no sequestro relâmpago, quem paga é o próprio dono da conta, no próprio celular, e ele passaria no 2FA. Com uma nota única, o motor pediria 2FA justamente onde o 2FA não protege.

### O caminho de um Pix

```
POST /pix/transaction
  │
  ├─ 1. Schema (JSON Schema, como no base-service)          → 400 se o corpo vier errado
  ├─ 2. Idempotência: esse id já foi analisado?             → devolve a análise gravada (200)
  │                                                           mesmo id com outro corpo → 409
  ├─ 3. Histórico: 2 consultas indexadas, antes das regras
  │       • os últimos Pix do PAGADOR (até 500, em 90 dias)
  │       • o DESTINO agregado (pagadores distintos na última hora, recusas no último mês)
  ├─ 4. Motor (src/rules/): 16 regras puras, sem banco
  ├─ 5. Decisão: notas dos dois eixos → status
  └─ 6. Grava Pix + análise + cada regra disparada, num commit só  → 201
```

- **Uma ida ao banco por Pix, e só índices.** O Pix tem poucos segundos para a cadeia inteira, e o Banco Central acompanha o p95 e o p99 do tempo de resposta. Por isso o histórico vem de uma vez, antes das regras. O tempo do motor fica gravado em toda análise (`decision_latency_ms`). Nos testes locais, o p95 ficou em torno de 6 ms.
- **As regras são Python puro.** Elas recebem o Pix e o histórico e devolvem um disparo ou nada, sem banco, rede ou relógio. Isso as deixa rápidas, testáveis em milissegundos e determinísticas.
- **O relógio das regras é a `transaction_date` do Pix**, com o fuso que veio, e não o relógio do servidor. "Últimos 10 minutos" quer dizer os 10 minutos antes *deste* Pix, e "noite" quer dizer a noite no relógio de quem paga.

### Pontos em vez de uma fila de ifs

Com ifs, cada sinal fraco decide sozinho. Bloquear todo Pix para conta aberta há menos de 7 dias travaria todo mundo que paga um prestador novo. Com pontos, um sinal fraco só pesa somado a outros, e cada ponto continua explicável: o `metadata` lista cada regra que disparou, quanto somou e os números que ela viu.

Os casos em que um sinal sozinho já é risco claro, como dez Pix em dez minutos ou uma conta recebendo de dez pessoas na mesma hora, continuam existindo como regras de **bloqueio**.

## Regras

Valores em reais. No código e no contrato, todo dinheiro é centavos em inteiro. Todos os números estão em [`src/rules/parameters.py`](services/antifraud-service/src/rules/parameters.py), versionados (`rules_version` vai em cada análise). A QI Tech recalibra regras toda semana, e calibrar aqui é mexer num arquivo só.

### Eixo identidade — "quem é essa pessoa?"

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **ID01** Dispositivo novo | O `device_id` nunca apareceu no histórico do pagador | +30 se o pagador tem histórico; +10 se é o primeiro Pix que o motor vê dele | Trocar de aparelho é o primeiro passo do roubo de conta: o fraudador entra com a senha num celular dele. No primeiro Pix do pagador tudo é novo, inclusive o aparelho. Pontuar cheio aí puniria o cliente pelo nosso *cold start*. |
| **ID02** Limite de dispositivo não cadastrado | Aparelho sem nenhum Pix **aprovado** deste pagador **e** (Pix > R$ 200 **ou** soma do aparelho em 24 h > R$ 1.000) | R$ 200 por Pix, R$ 1.000 por dia. Efeito: **piso de 2FA**, sem pontos | É a norma citada na apresentação: dispositivo não cadastrado tem teto, e acima dele o banco precisa da prova de vida, que é exatamente o 2FA. O motor não recebe o cadastro de dispositivos, então usa o próprio histórico como cadastro: o aparelho vira confiável depois de um Pix aprovado. É regra, não suspeita, por isso força 2FA em vez de somar pontos. Pix recusado não conta na soma nem torna o aparelho confiável. |
| **ID03** Viagem impossível | Distância até o último Pix com geolocalização ÷ tempo entre eles > 900 km/h, com distância ≥ 100 km | 900 km/h, 100 km, +45 | 900 km/h é a velocidade de um avião comercial. Abaixo de 100 km é ruído de GPS ou de IP. São Paulo e, meia hora depois, Manaus: ou são duas pessoas, ou a localização é falsa. A geolocalização é opcional no contrato, então a regra só roda quando os dois Pix a trazem. |
| **ID04** Rajada | Pix do pagador nos últimos 10 min, **contando os recusados**, mais o atual | ≥ 5: +30 · ≥ 10: **bloqueio** | Cliente de verdade não manda dez Pix em dez minutos. Quem esvazia uma conta roubada, ou um robô, manda. As recusas entram na conta porque insistir depois de uma recusa é o próprio sinal. Cinco pede confirmação; dez é risco claro. |
| **ID05** Canal novo | Pagador com ≥ 5 Pix e canal nunca usado | +10 | Sinal fraco sozinho (o cliente pode trocar de canal), por isso vale pouco e só pesa somado. No internet banking o banco não consegue amarrar o aparelho, e é onde o fraudador prefere operar. |
| **ID06** Madrugada fora do hábito | Pix entre 0h e 5h (hora local) de pagador com ≥ 10 Pix e nenhum nessa faixa | +15 | O "está no padrão do cliente?" do enunciado, olhando o horário. Exige histórico para existir um hábito. |

### Eixo transação — "a transação é legítima?"

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **TX01** Destino recém-aberto | Idade da conta de destino na data do Pix | ≤ 7 dias: +25 · ≤ 30 dias: +15 | Conta laranja tem vida curta: é aberta, recebe o dinheiro do golpe e é abandonada. É o sinal mais barato do payload, porque não custa consulta. Sozinho não chega a 30 pontos, então não trava quem paga um prestador novo. |
| **TX02** Conta laranja | Pagadores **distintos** para a mesma conta (ISPB + agência + conta) na última hora, contando o atual | ≥ 5: +40 · ≥ 10: **bloqueio** | É a conta laranja vista do lado de quem recebe. Nenhuma vítima parece estranha sozinha; o destino parece. Cinco pessoas diferentes numa hora já é incomum para pessoa física; dez é padrão de golpe em massa. |
| **TX03** Destino com recusas | Pix recusados para esta conta nos últimos 30 dias | ≥ 1: +25 · ≥ 3: +45 | O motor aprende com as próprias decisões. Um destino barrado continua suspeito para os próximos pagadores, mesmo que eles não tenham nada de estranho. |
| **TX04** Valor fora do perfil | Pix ÷ **maior** Pix aprovado do pagador (exige ≥ 5 aprovados) | > 2×: +25 · > 5×: +40. Sem perfil: > R$ 5.000 soma +15 | Compara com o maior Pix, e não com a média, porque a média puniria quem paga o aluguel uma vez por mês e faz Pix pequenos o resto do tempo. "Mais que o dobro do maior Pix que você já fez" é fácil de explicar ao cliente e difícil de acontecer por acaso. |
| **TX05** Soma do dia fora do padrão | Total das últimas 24 h vs. média diária dos 29 dias anteriores (exige 1 semana de histórico) | > 3× a média **e** > R$ 2.000: +25 | Pega o que o TX04 não vê: vários Pix médios que, somados, esvaziam a conta. O piso de R$ 2.000 evita disparar para quem quase não movimenta (3× de quase nada continua sendo quase nada). |
| **TX06** Fracionamento | ≥ 3 Pix na última hora entre 90% e 100% de um limite conhecido (R$ 200 do aparelho, R$ 1.000 da noite) | 90–100%, 3 Pix, +30 | Quem conhece o teto quebra o valor em pedaços de R$ 199. Cada pedaço passa nas regras de limite; a repetição dentro da faixa é que denuncia. |
| **TX07** Limite noturno | Pagador pessoa física (CPF), entre 20h e 6h na hora local, soma da noite > R$ 1.000 | R$ 1.000, +35 | O limite noturno do Pix existe por causa do sequestro relâmpago. A vítima está com o celular, desbloqueia com o próprio rosto e passaria no 2FA. Por isso a regra mora no eixo da **transação**. Soma a noite inteira para não ser driblada com vários Pix menores, e não vale para CNPJ, que tem outra regra. |
| **TX08** Primeiro Pix para o recebedor | Pagador com histórico, recebedor (CPF/CNPJ) nunca pago, Pix ≥ R$ 1.000 | +10 | Sozinho é o dia a dia, e por isso vale pouco. Existe para somar: destino novo + valor alto + primeira vez é o retrato do golpe. Não roda no primeiro Pix do pagador (para ele, todo recebedor é o primeiro). |

### Confiança — descontam do eixo da transação

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **TR01** Recebedor recorrente | ≥ 3 Pix **aprovados** para o mesmo CPF/CNPJ | −30 | Bloquear um cliente bom também é prejuízo. Sem confiança, quem paga o aluguel todo mês para o mesmo dono esbarraria nas mesmas regras que um golpista. |
| **TR02** Mesma titularidade | CPF/CNPJ de origem = destino | −20 | Mandar dinheiro para a própria conta em outro banco é rotina. |

A confiança **não desconta da identidade**. Pagar sempre a mesma pessoa não prova que é o dono da conta quem está pagando: um ladrão com o celular desbloqueado também paga o aluguel de alguém. A nota de nenhum eixo fica negativa.

## Como as regras viram decisão

Na ordem, a primeira que valer decide:

| # | Condição | Status | Por quê |
|---|---|---|---|
| 1 | Alguma regra de **bloqueio** disparou (ID04 ≥ 10, TX02 ≥ 10) | `rejected` | Risco claro, que não precisa de soma. |
| 2 | Transação **≥ 60** | `rejected` | O 2FA confirmaria quem paga, mas não torna a transação legítima. |
| 3 | Identidade **≥ 80** | `rejected` | Sinais tão fortes (ex.: viagem impossível + aparelho novo + rajada) que nem o 2FA convence, porque pode haver troca de chip. |
| 4 | Identidade **≥ 40** e transação **≥ 40** | `rejected` | Dúvida séria sobre quem *e* sobre o quê: o retrato do roubo de conta. |
| 5 | Algum eixo **≥ 30**, ou piso de 2FA (ID02) | `two_factor_required` | Fricção só onde há dúvida. |
| 6 | Nada disso | `approved` | Segue sem fricção. |

**Quando pede 2FA:**
- **Dúvida sobre identidade (30–79).** É o uso clássico: o cliente confirma com o rosto que é ele e segue.
- **Dúvida sobre a transação (30–59).** Aqui o 2FA funciona como **pausa de confirmação**: quem está sendo enganado ao telefone ganha um momento para pensar, e a tela pode avisar "você conhece quem vai receber?". Acima de 59 a pausa não basta e o motor recusa.
- **Aparelho não cadastrado acima do teto (ID02)**, por regulação.

**A assimetria é a escolha central do motor.** Com 60 pontos, a dúvida sobre *quem* ainda se resolve com 2FA; a dúvida sobre *o quê*, não. O eixo da transação recusa em 60 e o da identidade em 80 exatamente por isso.

**Se uma regra quebrar** (uma exceção no código), a análise não cai. O motor registra o erro nos motivos e põe um piso de 2FA. Aprovar às cegas liberaria fraude; recusar travaria cliente bom por defeito nosso.

### Exemplos (rodam em `scripts/demo.py`)

| Cenário | Identidade | Transação | Decisão |
|---|---|---|---|
| Aluguel de R$ 1.500 para o mesmo dono, pela 4ª vez | 0 | 0 (TR01 −30) | `approved` |
| R$ 150 para o mercado de sempre, de um celular novo | 30 (ID01) | 0 | `two_factor_required` |
| Exemplo do enunciado: R$ 1.500 às 22h15, destino de 7 dias, primeiro Pix | 10 | 50 (TX01 + TX07) | `two_factor_required` |
| Golpe: aparelho de sempre, R$ 3.000 para conta aberta há 2 dias | 0 | 100 | `rejected` |
| 10º pagador diferente em uma hora para a mesma conta | 10 | 0 | `rejected` (TX02 bloqueio) |

### O que foi decidido onde o enunciado não dizia

- **Pix que pediu 2FA conta como dinheiro que saiu.** O desafio não tem retorno do resultado do 2FA. Para soma do dia, limite noturno e teto do aparelho, subestimar o que saiu é o erro perigoso, então o 2FA entra na soma. Para confiança (TR01, aparelho confiável no ID02, perfil no TX04) só conta o que foi **aprovado**, porque nesse caso o erro perigoso é o contrário. Com um endpoint de resultado do 2FA, esses Pix passariam a contar como aprovados ou recusados: é o primeiro próximo passo.
- **Cold start.** No primeiro Pix de um pagador o motor não sabe nada sobre ele. As regras de perfil exigem histórico mínimo e ficam neutras sem ele, em vez de contar contra o cliente.
- **Documento com ou sem pontuação** é a mesma pessoa: tudo é gravado só com dígitos. O motor não recusa por dígito verificador, porque quem chega ao Pix já passou pelo onboarding, que está fora do escopo.
- **`transaction_date` sem fuso é 422.** Sem fuso, "22:15" não diz se é noite para quem pagou.
- **O mesmo `id` duas vezes** devolve a análise original (200), sem reanalisar. Com outro corpo é 409, e a análise original fica: o cliente já viu aquela decisão.

### Modelagem de dados

```
pix_transactions   o que chegou: o Pix normalizado (documento só dígitos, data com fuso)
       │ 1:1
pix_analyses       o que decidimos: status, nota de cada eixo, motivo, versão das regras, latência
       │ 1:N
rule_hits          por que decidimos: cada regra disparada, eixo, efeito, pontos, motivo e evidência (JSONB)
```

- **A transação fica separada da análise.** Isso deixa reanalisar o mesmo Pix com outra versão das regras sem reescrever o que chegou.
- **As regras disparadas ficam separadas** para responder ao cliente que liga perguntando "por que bloquearam meu Pix?": cada linha é um motivo, com os números daquele instante.
- **Tudo é só INSERT.** O histórico é a matéria-prima das regras e o registro do que foi dito ao cliente.
- **Cada índice existe por causa de uma regra:**
  - `(source_document, transaction_date)` para o histórico do pagador;
  - `(source_document, device_id, …)` para aparelho;
  - `(participant, branch, account_number, transaction_date)` para conta laranja e recusas;
  - `(source_document, destination_document)` para recorrência.
- Status e eixo são tabelas de domínio, como no base-service. O schema completo e comentado está em [`database/database.sql`](services/antifraud-service/database/database.sql).

### Estrutura

O serviço segue as camadas do `bootcamp-base-api`: middlewares, `schemas/` (JSON Schema), `resources/` (HTTP), `controllers/` (orquestra e dá o commit), `repositories/` (única porta do banco), `models/`, `dtos/` e `errors/` com códigos QIT. A camada nova é **`rules/`**, o motor:

```
services/antifraud-service/src/rules/
├── parameters.py        todos os números, versionados
├── context.py           o que o motor enxerga (Pix + histórico)
├── rule.py              o formato comum de uma regra
├── identity_rules.py    ID01–ID06
├── transaction_rules.py TX01–TX08
├── trust_rules.py       TR01–TR02
└── engine.py            roda as regras, soma os eixos, decide
```

Regra nova é uma classe nova na lista, e o motor não muda.

## Como rodar e testar

Pré-requisitos: Docker com Compose e Python 3.11.

```bash
docker compose up -d --build --wait          # sobe o banco e o serviço na porta 8005

python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt    # Windows: .venv\Scripts\pip

.venv/bin/pytest -v                          # unitários do motor + integração pela API
.venv/bin/python scripts/demo.py             # os cinco cenários da tabela acima
```

Nenhum passo manual: o `.env` é opcional (os padrões estão no `docker-compose.yml` e em `.env.example`). Mudou o `database.sql`? Rode `docker compose down -v`, porque o banco só executa o `.sql` ao nascer.

**Os testes:**
- [`services/antifraud-service/tests/unit`](services/antifraud-service/tests/unit) tem os testes do motor sem banco. Cada regra é testada no limite e logo abaixo dele, e a tabela de decisão é testada com regras falsas. Para rodar só esses, sem Docker: `pytest services/antifraud-service/tests`.
- [`tests/integration`](tests/integration) fala só HTTP. Cobre o contrato (formato, idempotência, 409, 400, 422, 403, 404, GET igual ao POST) e as jornadas de ponta a ponta, com o histórico montado por POSTs com datas no passado. O banco não precisa ser limpo: cada teste inventa os próprios CPFs e contas.

**Chamando na mão.** Todas as rotas, menos `/` e `/health_check`, exigem o cabeçalho `INTERNAL-TOKEN`, como no base-service. O motor é chamado pelo orquestrador do Pix, nunca pelo app do cliente.

```bash
curl -s -X POST localhost:8005/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" -H "Content-Type: application/json" \
  -d '{"id":"pix-000123","amount":150000,"transaction_date":"2026-10-17T22:15:00-03:00",
       "source_account":{"branch":"0001","account_number":"88213","opening_date":"2025-03-02T10:00:00-03:00",
                         "owner":{"document_number":"123.456.789-09"}},
       "destination_account":{"participant":"60701190","branch":"3675","account_number":"10442",
                              "opening_date":"2026-10-10T09:00:00-03:00",
                              "owner":{"document_number":"987.654.321-00"}},
       "source":{"device_id":"dvc-9f2c71a8","channel":"app","ip":"198.51.100.23",
                 "geolocation":{"latitude":-23.56,"longitude":-46.65}}}'

curl -s localhost:8005/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

| Resposta | Quando |
|---|---|
| 201 | Pix novo, analisado e gravado |
| 200 | Mesmo Pix repetido (devolve a análise original) ou GET |
| 400 `QIT000001` | Corpo fora do contrato (campo faltando, desconhecido, valor não inteiro) |
| 403 `QIT000002` | Sem `INTERNAL-TOKEN` |
| 404 `QIT003004` | GET de um Pix que nunca chegou |
| 409 `QIT003009` | Mesmo `id` com outro corpo |
| 422 `QIT003022` | Data sem fuso horário |
