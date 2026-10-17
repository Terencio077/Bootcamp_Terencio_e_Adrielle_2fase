# Testes adicionais — Antifraude Pix v3

Criados em 17/10/2026 para complementar a revisão do Hackathon QI Tech.

Base exata: `antifraude-pix-v3.zip`, SHA-256
`b12fde9bad189f724db616c3685715248eb891ee19e8c81f0c8f625856995c7f`.

Este pacote acrescenta somente a pasta `testes_revisao_v3/`. Não substitui o
motor, os parâmetros, as dependências ou os testes existentes. A pasta fica
fora dos `testpaths` originais; rode-a explicitamente com a configuração abaixo.

## Resultado obtido

| Verificação | Resultado |
|---|---|
| Unitários que já vieram na v3 | 92 passaram |
| Coleta original, incluindo integração | 123 encontrados: 92 unitários + 31 de integração |
| Novos testes deste pacote | 28 executados: 24 passaram e 4 falharam |
| Causas distintas das quatro falhas | 3 |
| Integração HTTP e concorrência real em PostgreSQL | Não executadas nesta revisão |

Os quatro testes vermelhos estão ativos, sem `skip` ou `xfail`. O comando
terminar com código 1 na v3 é esperado: ele registra problemas que ainda
precisam ser corrigidos. Não remova as asserções apenas para a suíte ficar verde.

Ambiente usado: Python 3.12.14, pytest 7.4.4, SQLAlchemy 2.0.23 e versões fixadas
nos dois arquivos de requirements do projeto, em venv separado. Não houve
alteração de dependências do projeto. Os testes SQL geram avisos de depreciação
do adapter de datetime do SQLite/Python; esses avisos não são as quatro falhas.

## Como usar

Extraia o ZIP **na raiz do projeto**, ao lado de `services/`, `tests/` e do README
principal. Não é preciso trocar o código pela cópia de quem fez a revisão.

Com o ambiente do projeto já ativo:

```bash
python -m pip install -r services/antifraud-service/requirements.txt -r requirements-dev.txt
python -m pytest -c testes_revisao_v3/pytest.ini testes_revisao_v3 -q --tb=short
```

Se preferir criar um ambiente separado:

```bash
python -m venv .venv-revisao
```

No Linux/macOS, ative com `source .venv-revisao/bin/activate`. No PowerShell,
use `.venv-revisao\Scripts\Activate.ps1`. Depois execute os dois comandos acima.

O `-c` mantém a suíte isolada do `pythonpath = tests` da configuração original.
Esse caminho contém um pacote `utils` de testes que conflita com o namespace
`utils` usado pelo serviço. A configuração nova resolve isso para esta suíte
sem editar a configuração do projeto. Execute a suíte HTTP original separadamente.

Para ver apenas as falhas, executar um grupo ou conferir os unitários originais:

```bash
python -m pytest -c testes_revisao_v3/pytest.ini testes_revisao_v3 --lf -q --tb=short
python -m pytest -c testes_revisao_v3/pytest.ini testes_revisao_v3/test_tx03_consulta.py -v
python -m pytest services/antifraud-service/tests -q
```

## Falha 1 — duplicidade detectada no flush

**Dois testes falham, com a mesma causa.**

- `test_duplicidade_detectada_no_flush_devolve_analise_existente`
- `test_duplicidade_no_flush_com_corpo_diferente_gera_conflito`

O controller chama `PixRepository.save()` antes do `try` que captura
`IntegrityError`. O `save()` real já chama `session.flush()`. Se a duplicidade
for detectada nesse momento, a exceção escapa antes do tratamento de idempotência.

Os testes executam o controller e o método de gravação reais e simulam uma
violação de unicidade no flush. O resultado esperado é recuperar a análise
existente, ou devolver conflito quando o corpo mudou. A v3 propaga `IntegrityError`
nos dois casos. O caso equivalente com erro no commit passa.

Correção sugerida: abranger `save()` e `commit()` no tratamento, fazer rollback
antes da releitura e preservar o conflito de corpo diferente. Se não existir
análise para recuperar, propagar a falha original. Uma releitura após adquirir
as travas também evita reanálise desnecessária quando a primeira chamada já terminou.

Esses testes não provam como duas conexões PostgreSQL se comportam em paralelo.
Depois da correção, testar dois POSTs simultâneos com mesmo ID/corpo e mesmo
ID/corpos diferentes no serviço real.

## Falha 2 — três offsets fabricam três dias de recorrência

Teste: `test_mesmo_instante_em_tres_offsets_nao_pode_fabricar_tres_dias_de_relacao`.

Três pagamentos diferentes são representados no mesmo instante:

| Data informada | Instante equivalente |
|---|---|
| 2026-10-13 23:30:00 -12:00 | 2026-10-14 11:30:00 UTC |
| 2026-10-14 11:30:00 +00:00 | 2026-10-14 11:30:00 UTC |
| 2026-10-15 01:30:00 +14:00 | 2026-10-14 11:30:00 UTC |

TR01 usa `.date()` de cada pagamento, com seu próprio offset. Ela conta três
datas e concede -30 pontos, embora todos os instantes sejam iguais. A mesma
entrada normalizada para UTC não recebe o desconto.

Correção sugerida: escolher e documentar uma referência temporal comum para
contar dias do relacionamento. Pode ser um fuso de negócio estável ou UTC.
Converter todos os instantes para essa referência antes de extrair a data.
Isso não exige mudar a regra noturna, cujo objetivo é diferente. Aplicar o
mesmo cuidado às demais contagens de dias, como recorrência de dispositivo.

O teste usa entradas temporalmente válidas e não afirma que offsets tão
distantes sejam comuns. Ele verifica que mudar a representação do mesmo
instante não cria evidência de relacionamento de vários dias.

## Falha 3 — REJECT da própria TX03 entra pelo ramo EXISTS

Teste: `test_reject_da_propria_tx03_tambem_deve_ser_excluido_do_autorreforco`.

A soma de pontos no SQL exclui `rule_code = 'TX03'`, mas o ramo `OR EXISTS`,
que aceita efeitos `REJECT`, não tem a mesma exclusão.

Na v3 esse caso é excepcional: uma falha da TX03 em valor de pelo menos
R$ 1.000 faz `DecisionEngine.failure_hit()` produzir um hit
`TX03 / TRANSACTION / REJECT / 0`. Se ele for persistido, a consulta posterior
o conta como reputação negativa do destino. O teste esperava zero e recebeu um.
Dois pagadores distintos nessa situação atingiriam o gatilho da TX03.

Correção mínima sugerida: excluir a própria TX03 também no ramo `EXISTS`.
Avaliar adicionalmente se recusas por falha técnica de qualquer regra devem
ser excluídas dessa reputação. Uma decisão de segurança por erro não é, por
si só, evidência de fraude do recebedor.

A consulta real foi executada contra tabelas mínimas em SQLite. Isso verifica
a lógica de filtros e agregações usada no caso, mas não certifica schema,
tipos, índices, planos de execução ou concorrência em PostgreSQL.

## O que os casos aprovados verificaram

- Novo ID após 2FA, fora da janela de rajada, continua exigindo desafio.
- Pix pequeno não libera o aparelho um segundo antes do prazo de 24 horas.
- Comércio com 35 pagadores e relacionamento recorrente aprova compra pequena.
- No mesmo comércio, sem relacionamento, volume gera confirmação e não recusa isolada.
- CNPJ antigo continua sujeito à combinação de outros sinais fortes.
- Recorrência e mesma titularidade, juntas, não removem o piso noturno.
- Limites exatos de início e fim da janela noturna.
- Desconto de confiança não esconde fallback de regra na fronteira de valor.
- Erros de data identificam os três campos corretamente.
- Falha na leitura de histórico não gera uma falsa decisão de risco.
- TX03 ignora recusas de identidade, desconta confiança no cálculo sem TX03,
  não conta múltiplas recusas da mesma pessoa como várias pessoas e filtra
  destino, janela e status.

O resultado de cada caso está em `RESULTADOS.md` e no XML do pytest.

## Dois experimentos de política, separados dos testes de regressão

```bash
python testes_revisao_v3/explorar_politicas.py
```

Esse script imprime decisões do motor real, sem afirmar que uma política
específica é obrigatória. Não é coletado pelo pytest.

| Experimento | Resultado observado na v3 | Questão para o time |
|---|---|---|
| R$ 50 aprovados no aparelho; R$ 500 após 24 horas e um segundo | Segundo Pix aprovado, ID=0 e TX=0 | O prazo adia o atalho; qual evidência autoriza chamar o aparelho de confirmado? |
| Três Pix de R$ 1 em dias distintos para destino antigo, com histórico prévio do pagador; depois R$ 5.000 | Aprovado, TX04 +40 e TR01 -30, total TX=10 | O desconto deve ter condições de materialidade e compatibilidade com o valor atual? |

Os pagamentos que formam esses históricos também são avaliados e aprovados
pelo motor no script. Os cenários não incluem resultado de autenticação externa.
São padrões de preparação possíveis, não amostras rotuladas de fraude real.
Não foram classificados como falhas técnicas porque reproduzem as políticas
explicitamente escolhidas na v3. Alterar essas políticas exige uma decisão do
time e cenários legítimos de comparação, sem inventar limiares “ótimos”.

## Próximo ciclo com o Claudio

1. Corrigir as três causas, preservando os testes que as reproduzem.
2. Reexecutar os 28 casos e os unitários existentes.
3. Subir serviço e PostgreSQL e executar a suíte HTTP original, incluindo
   os novos cenários de duplicidade simultânea a acrescentar nela.
4. Decidir as duas políticas exploratórias e documentar o racional e os limites.

Esta entrega contém testes e reproduções; não contém correções do motor.
