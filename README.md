# [Nome do grupo]

**Integrantes:** [nomes]

Motor antifraude de Pix: uma API que recebe um Pix, olha o histórico de quem paga e de quem recebe, aplica as regras e devolve `approved`, `two_factor_required` ou `rejected`, com o motivo de cada decisão gravado e consultável.

> **Estado deste documento.** As regras e os parâmetros abaixo foram escolhidos por raciocínio e revisados contra cenários de fraude e cenários legítimos parecidos com elas. Os números ainda não foram calibrados com uma bateria completa de cenários; os que são hipótese estão marcados como tal.

## Como o motor de decisão funciona

### Duas perguntas, dois eixos

A apresentação da QI Tech fez duas perguntas diferentes: **"quem é essa pessoa?"** e **"essa transação é legítima?"**. O motor responde cada uma num eixo próprio, com uma nota de 0 a 100+:

| Eixo | Pergunta | Exemplos de sinal |
|---|---|---|
| **Identidade** | É mesmo o dono da conta? | aparelho não confirmado, viagem impossível, rajada de Pix |
| **Transação** | Mesmo sendo ele, o Pix é legítimo? | conta de destino recém-aberta, concentração de pagadores, valor fora do perfil |

A separação existe porque **as três decisões não resolvem as duas dúvidas do mesmo jeito**. O 2FA prova *quem* está pagando. Ele não prova que o Pix é legítimo. No golpe do falso parente, no falso funcionário do banco ou no sequestro relâmpago, quem paga é o próprio dono da conta, no próprio celular, e ele passaria no 2FA. Com uma nota única, o motor pediria 2FA justamente onde o 2FA não protege.

### O caminho de um Pix

```
POST /pix/transaction
  │
  ├─ 1. Schema (JSON Schema, como no base-service)          → 400 se o corpo vier errado
  ├─ 2. Idempotência: esse id já foi analisado?             → devolve a análise gravada (200)
  │                                                           mesmo id com outro corpo → 409
  ├─ 3. Trava de concorrência por pagador (advisory lock do Postgres)
  ├─ 4. Histórico: 3 consultas indexadas, antes das regras
  │       • os últimos Pix do PAGADOR (até 500, em 90 dias)
  │       + agregados no banco: 1º Pix do pagador e soma de 30 dias
  │       • quantos pagadores DIFERENTES tentaram pagar o destino na última hora
  │       • quantos pagadores diferentes tiveram Pix para o destino recusado por risco da transação
  ├─ 5. Motor (src/rules/): 16 regras puras, sem banco
  ├─ 6. Decisão: notas dos dois eixos + pisos regulatórios → status
  └─ 7. Grava Pix + análise + cada regra disparada, num commit só  → 201
```

- **O histórico vem de uma vez e só por índices.** O Pix tem poucos segundos para a cadeia inteira, e o Banco Central acompanha o p95 e o p99 do tempo de resposta. Por isso o histórico vem antes das regras, em três consultas indexadas.
- **O tempo de decisão fica gravado em toda análise** (`decision_latency_ms`). Ele mede da trava até a decisão do motor (passos 3 a 6) e **não inclui** a validação do corpo nem a gravação e o commit. O tempo total de cada requisição aparece no log (`SAIU 201 ... ms`).
- **Medição feita até agora** (ambiente local, PostgreSQL 16, um processo): Pix isolados decidem em 3 a 6 ms, que é o que a demo mostra. Nas 214 análises da suíte de testes, o p95 ficou em ~20 ms, puxado pelo teste de concorrência, em que 12 Pix simultâneos do mesmo pagador esperam um pelo outro na trava. Sob volume, com 100 mil Pix de histórico, ver **`CARGA.md`**: 100 Pix/s de contas diferentes com p95 de 59 ms, 50 Pix/s para a mesma loja com p95 de 220 ms, e nenhum Pix sem decisão no mesmo pagador até 50 Pix/s. O teste de carga mudou três coisas no projeto: 4 processos, fim da trava do destino e a TX09.
- **As regras são Python puro.** Elas recebem o Pix e o histórico e devolvem um disparo ou nada, sem banco, rede ou relógio. Isso as deixa testáveis em milissegundos e determinísticas.
- **O relógio das regras é a `transaction_date` do Pix**, com o fuso que veio, e não o relógio do servidor. "Últimos 10 minutos" são os 10 minutos antes *deste* Pix; "noite" é a noite no relógio de quem paga.
- **Pix simultâneos do mesmo pagador não se atropelam.** Sem a trava do passo 3, dois Pix do mesmo pagador chegando juntos leem o histórico antes de qualquer um gravar, e a rajada conta errado. Isso foi reproduzido: 12 Pix simultâneos contaram a rajada como `[5, 5, 5, …]` em vez de `5…12`. A trava fila as análises do mesmo pagador. **O destino não é travado, de propósito:** uma versão anterior travava também o destino, e o teste de carga mostrou que isso colocava em fila todos os clientes de uma loja (acima de ~10 Pix/s para a mesma conta, os pagamentos estouravam o tempo). Em chegadas simultâneas, a TX02 pode ver um ou dois pagadores a menos numa janela de uma hora, o que não muda a decisão. Serializar o mesmo pagador não atrapalha ninguém legítimo: uma pessoa não manda dez Pix por segundo. A trava fica no Postgres, então vale também entre os 4 processos da API (`WEB_WORKERS` no Dockerfile).

### Pontos, pisos e combinação

Uma regra pode ter três efeitos:

- **Somar pontos** num eixo. Os pontos são positivos para suspeita e negativos para confiança.
- **Piso de 2FA.** Usado para limites regulatórios: abaixo dele o Pix não é aprovado, e **nenhum desconto de confiança o derruba**.
- **Bloqueio.** Nenhuma regra de hoje bloqueia sozinha.

Falhas técnicas têm efeitos próprios (`failsafe_reject`, `failsafe_two_factor`): a decisão é a mesma de um bloqueio ou de um piso, mas o registro deixa claro que foi defeito nosso, e nada que olhe o passado (como a TX03) conta isso como evidência de fraude.

Com ifs, cada sinal fraco decidiria sozinho. Bloquear todo Pix para conta aberta há menos de 7 dias travaria todo mundo que paga um prestador novo. Mesmo sinais que parecem "risco claro" aparecem em gente legítima: dez Pix em dez minutos é o churrasco dividido entre amigos, e dez pagadores numa hora é a lanchonete no almoço. **A recusa sai da combinação de sinais**, e cada ponto continua explicável: o `metadata` lista cada regra que disparou, quanto somou e os números que ela viu.

## Regras

Valores em reais. No código e no contrato, todo dinheiro é centavos em inteiro. Todos os números estão em [`src/rules/parameters.py`](services/antifraud-service/src/rules/parameters.py), versionados (`rules_version` vai em cada análise).

### Confiança do aparelho (usada pela ID01 e pela ID02)

O contrato não traz o resultado do 2FA nem o cadastro de dispositivos. Um Pix que pediu 2FA pode ter sido confirmado ou abandonado, e o motor não sabe. Por isso **só a aprovação confirma um aparelho**: tempo, repetição ou uma tentativa pendente nunca viram confirmação.

| Estado | Critério |
|---|---|
| **Novo** | Nunca apareceu no histórico deste pagador. |
| **Observado** | Já apareceu, mas não tem Pix aprovado com 24 h de idade. |
| **Uso recorrente** | Observado em ≥ 3 dias diferentes, ao longo de ≥ 7 dias, sem nenhuma recusa. **Indica histórico de uso, não identidade comprovada**, e só reduz a suspeita. *(hipótese a calibrar)* |
| **Confiável** | Tem um Pix **aprovado** a partir dele há pelo menos 24 h. |

As 24 h impedem o atalho de aprovar um Pix de R$ 50 e, minutos depois, mandar R$ 500 do mesmo aparelho.

### Eixo identidade — "quem é essa pessoa?"

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **ID01** Dispositivo não confiável | O aparelho não está **confiável** para este pagador | +30 se o pagador tem outro aparelho confiável (troca de aparelho); +15 se o aparelho está em uso recorrente; +10 se o pagador ainda não tem nenhum aparelho confiável | Trocar de aparelho é o primeiro passo do roubo de conta. "Já vimos este aparelho" não basta, porque uma tentativa que pediu 2FA não prova nada: o segundo Pix do celular novo, minutos depois do primeiro, continua pedindo 2FA. O uso recorrente evita que um celular novo legítimo peça 2FA para sempre, sem fingir que isso é uma confirmação. No cold start, tudo é novo para o motor, e pontuar cheio puniria o cliente por isso. |
| **ID02** Limite de dispositivo não cadastrado | Aparelho **não confiável** **e** (Pix > R$ 200 **ou** soma do aparelho em 24 h > R$ 1.000) | R$ 200 por Pix, R$ 1.000 por dia. **Piso de 2FA** | Os valores foram citados na apresentação: dispositivo não cadastrado tem teto, e acima dele o banco precisa da prova de vida, que é o 2FA. *Hipótese:* como o motor não recebe o cadastro de dispositivos, usa "aparelho confiável" no lugar dele. O uso recorrente não escapa do teto. Pix recusado não conta na soma. |
| **ID03** Viagem impossível | Distância até o último Pix com geolocalização ÷ tempo entre eles > 900 km/h, com distância ≥ 100 km | 900 km/h, 100 km, +45 | 900 km/h é a velocidade de um avião comercial. Abaixo de 100 km fica a margem de erro de geolocalização por IP, que pode errar dezenas de km. VPN pode gerar falso positivo, e por isso a regra pontua em vez de bloquear. Só roda quando os dois Pix trazem geolocalização, que é opcional no contrato. |
| **ID04** Rajada | Pix do pagador nos últimos 10 min, **contando os recusados**, mais o atual | ≥ 5: +30 · ≥ 10: +50 | Insistir depois de uma recusa é o próprio sinal, por isso as recusas entram na conta. Não bloqueia sozinha, porque dividir o churrasco com dez amigos é legítimo. O 2FA é a resposta certa aqui, porque também barra automação. Com outro sinal (ex.: aparelho não confiável, +30), passa de 80 e recusa. |
| **ID05** Canal novo | Pagador com ≥ 5 Pix e canal nunca usado | +10 | Sinal fraco sozinho, por isso vale pouco e só pesa somado. No internet banking o banco não consegue amarrar o aparelho. |
| **ID06** Madrugada fora do hábito | Pix entre 0h e 5h (hora local) de pagador com ≥ 10 Pix e nenhum nessa faixa | +15 | O "está no padrão do cliente?" do enunciado, olhando o horário. Exige histórico para existir um hábito. |

### Eixo transação — "a transação é legítima?"

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **TX01** Destino recém-aberto | Idade da conta de destino na data do Pix | ≤ 7 dias: +25 · ≤ 30 dias: +15 | Conta laranja tem vida curta. É o sinal mais barato do payload, porque não custa consulta. Sozinho não chega a 30, então não trava quem paga um prestador novo. |
| **TX02** Concentração de pagadores **acima do padrão da conta** | Pagadores **distintos** que **tentaram** pagar a mesma conta (ISPB + agência + conta) na última hora, contando o atual, **menos 1,5× o pico** de pagadores distintos numa hora que essa conta teve nos 30 dias anteriores. Só o **excesso** conta | Excesso **CPF:** ≥ 5: +25 · ≥ 10: +40. **CNPJ:** ≥ 15: +15 · ≥ 30: +30 | Concentração aparece numa conta laranja e num restaurante no almoço. O que separa os dois não é o documento (um golpista abre um MEI em uma semana), é o **passado da própria conta**: o restaurante lota todo dia, a laranja não recebia de ninguém. A conta sem passado tem pico zero e conta tudo. O tipo de documento ficou só como contexto secundário nos limites, para dar folga a um comércio recém-chegado. Não bloqueia sozinha: a conta de CPF aberta há 3 dias com dez pagadores recusa pela **combinação** com a TX01 (25 + 40 = 65), e a vendedora de marmita que recebe no CPF e já teve 12 clientes numa hora em dias anteriores é aprovada. Limite conhecido: uma laranja teria de simular um mês de movimento com muitos CPFs distintos para "aprender" um pico alto, o que é caro e ainda esbarra na TX01 e na TX03. |
| **TX03** Destino com recusas | Pagadores **diferentes** cujo Pix para esta conta foi recusado **por risco da transação** nos últimos 30 dias | ≥ 2 pagadores: +25 | Só contam recusas que se sustentavam pelo lado da transação **sem a própria TX03** (nem nos pontos, nem num bloqueio): a nota da transação sem ela chegou a 60, ou outra regra de transação bloqueou. Falhas técnicas não contam. Recusas causadas pelo pagador (viagem impossível, rajada) não mancham o recebedor, e a regra não se alimenta das próprias decisões. Uma vítima só não marca a conta, e o peso é limitado. |
| **TX04** Valor fora do perfil | Pix ÷ **maior** Pix aprovado do pagador (exige ≥ 5 aprovados) | > 2×: +25 · > 5×: +40. Sem perfil: > R$ 5.000 soma +15 | Compara com o maior Pix, e não com a média, porque a média puniria quem paga o aluguel uma vez por mês. "Mais que o dobro do maior Pix que você já fez" é fácil de explicar ao cliente. |
| **TX05** Soma do dia fora do padrão | Total das últimas 24 h vs. média diária dos 29 dias anteriores (exige 1 semana de histórico), **só quando é a soma que estoura** (média de 30 dias calculada no banco, sem o corte de 500) | > 3× a média **e** > R$ 2.000: +25 | Pega vários Pix médios que, somados, esvaziam a conta. O piso de R$ 2.000 evita disparar para quem quase não movimenta. Se o Pix atual sozinho já chega ao limite **e o que veio antes no dia ainda estava abaixo dele**, o caso é do TX04: contar o mesmo Pix nas duas regras puniria duas vezes um único pagamento grande. Esse problema foi descoberto pelo caso do empréstimo ao amigo, abaixo. A segunda condição fecha um furo apontado na revisão: sem ela, aumentar o valor do último Pix desligava a regra. |
| **TX06** Fracionamento | ≥ 3 Pix na última hora entre 90% e 100% de um limite conhecido (R$ 200 do aparelho, R$ 1.000 da noite) | 90–100%, 3 Pix, +30 | Quem conhece o teto quebra o valor em pedaços de R$ 199. A repetição dentro da faixa é que denuncia. |
| **TX07** Limite noturno | Pagador CPF, entre 20h e 6h (hora local), soma da noite > R$ 1.000 | R$ 1.000. **Piso de 2FA** + 35 pontos | Existe por causa do sequestro relâmpago, em que a vítima passaria no 2FA; por isso fica no eixo da transação. É **limite**, não suspeita: o piso não é derrubado pela confiança, e os pontos somam com outros sinais. Ver as hipóteses logo abaixo. |
| **TX08** Primeiro Pix para o recebedor | Pagador com histórico, recebedor (CPF/CNPJ) sem nenhum Pix **aprovado** antes (tentativa pendente ou recusada não conta), Pix ≥ R$ 1.000 | +10 | Sozinho é o dia a dia. Existe para somar: destino novo + valor alto + primeira vez é o retrato do golpe. |
| **TX09** Pix simultâneos demais do mesmo pagador | A análise esperou mais de 0,5 s na fila do pagador (a trava de concorrência) | Piso de 2FA, 0 pontos | Pix do mesmo pagador são analisados em fila, para a rajada e a soma do dia não contarem errado. Quem passa de 0,5 s na fila não fica sem resposta (começou em 2 s; o teste de carga mostrou que esperas longas esgotavam as conexões do banco): é analisado mesmo assim e pede confirmação. Encher essa fila exige ~25 Pix/s do mesmo CPF/CNPJ: um robô esvaziando a conta (o 2FA o barra) ou uma empresa mandando um lote de uma vez. O teste de carga mostrou que, sem isso, o banco recebia **timeout** (nenhuma decisão). As outras regras continuam valendo: um Pix de risco alto é recusado do mesmo jeito. **Pagamento em lote** (folha, repasse a vendedores) é outro produto: aprovação do lote com um único 2FA e envio em ritmo controlado. Fica fora do escopo deste motor, que analisa um Pix por vez. |

**Hipóteses do limite noturno.** O padrão regulatório é R$ 1.000 entre 20h e 6h para pessoa física e MEI, e o cliente pode mudar o horário para 22h–6h e pedir aumento do limite, que leva de 24 a 48 h. O contrato **não informa** a configuração do cliente, e o motor não presume que ela exista:
- usa o padrão e, acima dele, **pede confirmação** em vez de recusar um limite que talvez tenha sido elevado;
- aplica só a CPF, porque MEI não se distingue de outros CNPJs pelo payload.

Isso é a aproximação possível com os dados do contrato, **não o cumprimento completo da norma**. Numa integração real, o orquestrador consultaria o limite configurado do cliente.

### Confiança — descontam do eixo da transação

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| **TR01** Recebedor recorrente | Pix **aprovados** para o mesmo CPF/CNPJ em ≥ 3 **dias diferentes**, com o primeiro há **≥ 30 dias**, **e** o Pix atual até 5× o maior Pix aprovado para esse recebedor | −30 (acima de 5×: 0, com o motivo no metadata) | Bloquear cliente bom também é prejuízo: quem paga o aluguel todo mês não deveria esbarrar nas regras de golpe. "Dias diferentes" separa recorrência de "aquecimento", o golpe de mandar três Pix pequenos na mesma tarde antes do grande. **Materialidade (decisão do time):** um relacionamento pequeno não avaliza um valor muito maior, e três Pix de R$ 1 não avalizam R$ 5.000. Ver "Como escolhemos o 5×". Indica relacionamento, não identidade. |
| **TR02** Mesma titularidade | CPF/CNPJ de origem = destino | −20 | Mandar dinheiro para a própria conta em outro banco é rotina. |

A confiança **não desconta da identidade** (pagar sempre a mesma pessoa não prova quem está pagando) e **não derruba pisos regulatórios**. A nota de nenhum eixo fica negativa.

## Como as regras viram decisão

Na ordem, a primeira que valer decide:

| # | Condição | Status | Por quê |
|---|---|---|---|
| 1 | Bloqueio de regra, ou falha técnica em regra da transação com Pix ≥ R$ 1.000 | `rejected` | Ver "Se uma regra quebrar". |
| 2 | Transação **≥ 60** | `rejected` | O 2FA confirmaria quem paga, mas não torna a transação legítima. |
| 3 | Identidade **≥ 80** | `rejected` | Sinais tão fortes (ex.: aparelho não confiável + viagem impossível + canal novo) que nem o 2FA convence, porque pode haver troca de chip. |
| 4 | Identidade **≥ 40** e transação **≥ 40** | `rejected` | Dúvida séria sobre quem *e* sobre o quê: o retrato do roubo de conta. |
| 5 | Algum eixo **≥ 30**, ou piso de 2FA (ID02, TX07) | `two_factor_required` | Fricção só onde há dúvida, ou onde a regulação exige confirmação. |
| 6 | Nada disso | `approved` | Segue sem fricção. |

**A assimetria é a escolha central.** Com 60 pontos, a dúvida sobre *quem* ainda se resolve com 2FA; a dúvida sobre *o quê*, não. Por isso o eixo da transação recusa em 60 e o da identidade em 80. *Os limiares 30/40/60/80 são hipóteses a calibrar.*

**Quando a dúvida é da transação (30–59), o motor pede 2FA mesmo assim.** Ele não prova legitimidade; a aposta é que o 2FA funcione como uma pausa de confirmação no meio de um golpe. **Isso é hipótese e depende de como o app do banco implementa a tela**, por exemplo com um aviso do tipo "você conhece quem vai receber?". A API só devolve o status.

**Se uma regra quebrar** (uma exceção no código), a análise não cai, e o tratamento depende do eixo, coerente com a tese:
- **regra de identidade:** piso de 2FA, porque a dúvida que ficou é sobre quem paga;
- **regra de transação:** o 2FA não resolveria a dúvida. Recusa a partir de R$ 1.000 (dano potencial alto) e pede 2FA abaixo disso.

O erro fica gravado nos motivos, com o tipo da exceção.

### Exemplos (rodam em `scripts/demo.py`)

| Cenário | Identidade | Transação | Decisão |
|---|---|---|---|
| Aluguel de R$ 1.500 para o mesmo dono, pela 4ª vez | 0 | 0 (TR01 −30) | `approved` |
| R$ 150 para o mercado de sempre, de um celular novo | 30 (ID01) | 0 | `two_factor_required` |
| Golpe: aparelho de sempre, R$ 3.000 para conta aberta há 2 dias | 0 | 75 (TX01 + TX04 + TX08) | `rejected` |
| Conta de CPF aberta há 3 dias: 10º pagador diferente na hora | 10 | 65 (TX01 + TX02) | `rejected` |
| Vendedora de marmita no CPF, 12 clientes no almoço como em outros dias | 0 | 0 (dentro do próprio pico) | `approved` |
| Lanchonete antiga (CNPJ): 10º cliente diferente na hora | 10 | 0 | `approved` |
| Exemplo do enunciado: R$ 1.500 às 22h15, destino de 7 dias, primeiro Pix | 10 | 50 (TX01 + TX07) | `two_factor_required` (pisos ID02 e TX07) |

### Cada brecha tem dois testes

Na revisão do motor, cada furo encontrado virou um par de testes: o que reproduz o furo e um caso legítimo parecido com ele, para conferir que o conserto não trava gente boa.

| Brecha | Teste do furo | Caso legítimo parecido |
|---|---|---|
| Aparelho virava confiável depois de uma tentativa | 2º Pix do celular novo, 11 min depois do 2FA → continua 2FA | Celular novo usado por uma semana pontua menos; aparelho confirmado há 1 dia libera valor alto |
| Pix de R$ 50 aprovado liberava R$ 500 logo depois | R$ 500, 10 min depois → piso de 2FA | — |
| Conta laranja bloqueava comércio | CPF de 3 dias com 10 pagadores → recusa pela combinação | Lanchonete antiga com 10 clientes → aprovado; CPF novo com os primeiros clientes → 2FA, não recusa |
| Rajada bloqueava sozinha | Rajada de aparelho não confiável → recusa pela combinação | Churrasco com 10 amigos → 2FA, não recusa |
| Recusa do pagador manchava o recebedor | Dois pagadores recusados por risco da transação → TX03 | Recusas por viagem impossível do pagador → sem TX03; uma vítima só → sem TX03 |
| Limite noturno compensado por confiança | Noturno R$ 1.500 para recebedor recorrente → 2FA | Noturno R$ 900 para recebedor recorrente → aprovado |
| "Aquecimento" antes do Pix grande | 5 Pix na mesma tarde → não é recorrência | Pix em 3 dias diferentes → recorrência |
| Pix simultâneos contavam errado | 12 simultâneos → rajada conta 5…12 | — |
| Mesmo `id` simultâneo com corpos diferentes dava 500 | 6 chegadas → um 201 e cinco 409 | 6 chegadas iguais → um 201 e cinco 200, mesma `key` |
| Offsets diferentes fabricavam dias de recorrência | Mesmo instante em 3 offsets → não é recorrência | Pix em 3 dias diferentes → recorrência |
| Falha da própria TX03 voltava a contar contra o recebedor | Bloqueio da TX03 → não conta | Bloqueio de outra regra de transação → conta |
| 3 Pix de R$ 1 avalizavam R$ 5.000 | Aquecimento com R$ 1 ou R$ 600 → sem desconto, 2FA | Aluguel com reajuste, restante do empreiteiro → mantêm o desconto |
| Um Pix grande era contado duas vezes (TX04 + TX05) | — | Empréstimo de R$ 2.000 ao amigo de sempre → 2FA, não recusa |

### Como escolhemos o 5× da recorrência

O experimento da revisão externa mostrou que três Pix de R$ 1, em dias diferentes, davam o desconto de recorrência e faziam um Pix de R$ 5.000 ser aprovado (TX04 +40, TR01 −30). Decidimos que **um relacionamento pequeno não pode avalizar um valor muito maior**, e que a forma é a leve: acima do limite, o TR01 só deixa de descontar. A recorrência continua sendo um sinal; ela só não vale para um valor desproporcional.

Para escolher o limite, montamos casos legítimos e de golpe e comparamos quatro réguas. A conta é: valor atual ÷ maior Pix aprovado para o recebedor; ✅ = mantém o desconto.

| Caso | Proporção | 2× | 3× | 5× | 10× | Esperado |
|---|---|---|---|---|---|---|
| Aluguel com reajuste | 1,1× | ✅ | ✅ | ✅ | ✅ | manter |
| Restante do empreiteiro (entrada de 30%) | 2,3× | ❌ | ✅ | ✅ | ✅ | manter |
| Compra maior no mercado de sempre | 3× | ❌ | ✅ | ✅ | ✅ | manter |
| Empréstimo ao amigo de sempre (R$ 50 → R$ 2.000) | 40× | ❌ | ❌ | ❌ | ❌ | perder (2FA aceitável) |
| Golpe: aquece com 3× R$ 100, depois R$ 5.000 | 50× | ❌ | ❌ | ❌ | ❌ | perder |
| Golpe: aquece com 3× R$ 600, depois R$ 5.000 | 8,3× | ❌ | ❌ | ❌ | ✅ | perder |

- **2×** gera fricção em pagamentos legítimos;
- **10×** deixa passar o aquecimento com R$ 600;
- **3× e 5×** acertam todos os casos. Ficamos com **5×** por ser **a mesma régua do TX04**, que já trata "mais de 5× o maior Pix" como valor extremo. Assim o motor inteiro usa um critério só.

**Limites honestos:**
- os casos foram montados por nós, então mostram o raciocínio e não provam o número;
- nenhuma regra fecha tudo: aquecer abaixo de 5× continua possível. O que a regra faz é tornar o golpe mais caro, porque exige dias de preparação. O dinheiro do aquecimento vai para a conta do próprio fraudador, então o custo dele é o tempo, não o valor.

Todos os casos da tabela são testes em `tests/unit`.

**Tempo de relacionamento (decisão do time).** A bateria de calibração (`CALIBRACAO.md`) mostrou o único furo restante: aquecer com 3× R$ 600 em dias seguidos e depois mandar R$ 2.500 (abaixo de 5×) era aprovado. Decidimos que um relacionamento só vale depois de **30 dias desde o primeiro Pix aprovado** ao recebedor, que é o ciclo de uma conta mensal (aluguel, luz, escola). Três Pix em três dias seguidos ainda são um relacionamento novo. Com isso, a calibração passou de 29/30 para 30/30 sem travar nenhum legítimo, e o aquecimento agora exige um mês inteiro de preparação.

### Decisões onde o enunciado não dizia

- **Pix que pediu 2FA conta como dinheiro que saiu** nas somas (dia, noite, teto do aparelho), porque subestimar o que saiu é o erro perigoso. Para confiança (aparelho, recorrência, perfil), só conta o que foi **aprovado**. Um endpoint de resultado do 2FA permitiria tratar esses Pix com precisão, e é o primeiro próximo passo fora do escopo do desafio.
- **Cold start:** as regras de perfil exigem histórico mínimo e ficam neutras sem ele, em vez de contar contra o cliente.
- **Limite de 500 Pix no histórico do pagador.** Só afeta quem faz mais de 500 Pix em 90 dias. As janelas curtas (10 min, 24 h, a noite) continuam completas. O que dependia do histórico longo, a antiguidade do pagador e a média de 30 dias do TX05, é calculado direto no banco (`MIN` e `SUM`), então o corte não apaga essa evidência. Sem isso, um pagador intenso pareceria novo e o TX05 deixaria de funcionar para ele, ou seja, o corte reduziria a proteção, e não só aumentaria a fricção.
- **Documento com ou sem pontuação** é a mesma pessoa: tudo é gravado só com dígitos. O motor não recusa por dígito verificador, porque o onboarding está fora do escopo.
- **Data sem fuso é 422**, com o nome do campo na mensagem (`transaction_date` ou uma das `opening_date`). Sem fuso, "22:15" não diz se é noite para quem pagou. Os horários gravados pelo próprio serviço (`received_at`, `analysed_at`) também têm fuso.
- **O mesmo `id` duas vezes** devolve a análise original (200), sem reanalisar. Com outro corpo é 409, e a original fica: o cliente já viu aquela decisão. Isso vale também quando as chegadas são **simultâneas**: o serviço relê a análise depois de pegar a trava, e trata a duplicidade que o PostgreSQL acusa já no `flush`. Esse caso foi reproduzido: antes da correção, 5 de 6 chegadas simultâneas com o mesmo `id` e corpos diferentes recebiam 500.
- **Dias são contados no horário de Brasília (UTC−3).** Recorrência de recebedor e uso recorrente de aparelho contam "dias diferentes" num fuso único; senão, o mesmo instante escrito com três offsets diferentes viraria três dias. As regras de hora do dia (noite, madrugada) usam o fuso do próprio Pix, porque a pergunta delas é o relógio de quem paga. *Hipótese:* a `transaction_date` vem do core do banco, e não do aparelho do cliente.

### Modelagem de dados

```
pix_transactions   o que chegou: o Pix normalizado (documento só dígitos, data com fuso)
       │ 1:1
pix_analyses       o que decidimos: status, nota de cada eixo, motivo, versão das regras, tempo de decisão
       │ 1:N
rule_hits          por que decidimos: cada regra disparada, eixo, efeito, pontos, motivo e evidência (JSONB)
```

- **A transação fica separada da análise**, para permitir reanalisar o mesmo Pix com outra versão das regras sem reescrever o que chegou.
- **As regras disparadas ficam separadas** para responder ao cliente que liga perguntando "por que bloquearam meu Pix?". Elas também são o que deixa a TX03 olhar a **causa** de uma recusa antiga.
- **Tudo é só INSERT.**
- **Cada índice existe por causa de uma regra:**
  - `(source_document, transaction_date)` para o histórico do pagador;
  - `(source_document, device_id, …)` para aparelho;
  - `(participant, branch, account_number, transaction_date)` para concentração e recusas;
  - `(source_document, destination_document)` para recorrência.
- Status e eixo são tabelas de domínio, como no base-service. O schema comentado está em [`database/database.sql`](services/antifraud-service/database/database.sql).

### Estrutura

O serviço segue as camadas do `bootcamp-base-api`: middlewares, `schemas/` (JSON Schema), `resources/` (HTTP), `controllers/` (orquestra e dá o commit), `repositories/` (única porta do banco, inclusive a trava), `models/`, `dtos/` e `errors/` com códigos QIT. A camada nova é **`rules/`**, o motor:

```
services/antifraud-service/src/rules/
├── parameters.py        todos os números, versionados
├── context.py           o que o motor enxerga (Pix + histórico)
├── device.py            estados de confiança do aparelho
├── rule.py              o formato comum de uma regra
├── identity_rules.py    ID01–ID06
├── transaction_rules.py TX01–TX09
├── trust_rules.py       TR01–TR02
└── engine.py            roda as regras, soma os eixos, aplica pisos e decide
```

## Como rodar e testar

Pré-requisitos: Docker com Compose e Python 3.10+.

```bash
docker compose up -d --build --wait          # sobe o banco e o serviço na porta 8005

python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt    # Windows: .venv\Scripts\pip

.venv/bin/pytest -v                          # unitários do motor + integração pela API
.venv/bin/python scripts/demo.py             # os cenários da tabela de exemplos
```

Nenhum passo manual: o `.env` é opcional (os padrões estão no `docker-compose.yml` e em `.env.example`). Mudou o `database.sql`? Rode `docker compose down -v`, porque o banco só executa o `.sql` ao nascer.

**Os testes:**
- [`services/antifraud-service/tests/unit`](services/antifraud-service/tests/unit) tem os testes do motor sem banco: cada regra no limite e logo abaixo dele, os estados do aparelho, a tabela de decisão com regras falsas e os pares furo/caso legítimo. Para rodar só esses, sem Docker: `pytest services/antifraud-service/tests`.
- [`testes_revisao_v3`](testes_revisao_v3) tem os 28 testes da revisão externa (controller com falhas de banco simuladas e a consulta da TX03 em SQLite), com o relatório original. Rode com `pytest -c testes_revisao_v3/pytest.ini testes_revisao_v3`.
- [`tests/integration`](tests/integration) fala só HTTP. Cobre o contrato (formato, idempotência, 409, 400, 422, 403, 404, GET igual ao POST), as jornadas de ponta a ponta com o histórico montado por POSTs com datas no passado, e o teste de concorrência. O banco não precisa ser limpo: cada teste inventa os próprios CPFs e contas.

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
| 422 `QIT003022` | Data sem fuso horário (a mensagem diz qual dos três campos de data) |
