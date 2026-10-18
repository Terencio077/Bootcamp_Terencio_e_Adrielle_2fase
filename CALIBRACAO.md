# Bateria de calibração (simulação)

Gerado por `python scripts/calibracao.py`. Cenários montados pelo time, com o resultado aceitável definido **antes** de rodar o motor. Não são dados reais: mostram o raciocínio, não provam os números.

## Motor atual

- Acertos: **30/30**, conformidade com os cenários sintéticos que nós mesmos escrevemos. Não é taxa de acerto em dados reais.
- Legítimos recusados: **0** · legítimos com 2FA não previsto: **0**
- Fraudes aprovadas: **0** · fraudes que só pediram 2FA: **5**

| Cenário | Tipo | Aceitável | Motor | Ident. | Trans. | Regras | |
|---|---|---|---|---|---|---|---|
| Pix pequeno do dia a dia | legit | aprova | **aprova** | 0 | 0 |  | ✅ |
| Aluguel de sempre (4º mês) | legit | aprova | **aprova** | 0 | 0 | TR01-30 | ✅ |
| Aluguel com reajuste de 10% | legit | aprova | **aprova** | 0 | 0 | TR01-30 | ✅ |
| Pix para conta própria em outro banco | legit | aprova | **aprova** | 0 | 20 | TX04+40, TR02-20 | ✅ |
| Troca de celular, Pix pequeno | legit | 2fa/aprova | **2fa** | 30 | 0 | ID01+30 | ✅ |
| Troca de celular, aluguel | legit | 2fa | **2fa** | 30 | 0 | ID01+30, ID02, TR01-30 | ✅ |
| Compra cara excepcional (R$ 4.000, loja antiga) | legit | 2fa | **2fa** | 0 | 50 | TX04+40, TX08+10 | ✅ |
| Prestador novo (conta de 20 dias), R$ 300 | legit | 2fa/aprova | **2fa** | 0 | 40 | TX01+15, TX04+25 | ✅ |
| Cliente da lanchonete (CNPJ com 12 pagadores/h) | legit | aprova | **aprova** | 0 | 0 |  | ✅ |
| Autônomo com CPF novo recebendo 4 clientes/h | legit | 2fa/aprova | **aprova** | 0 | 15 | TX01+15 | ✅ |
| Churrasco: 6 amigos em 10 min | legit | 2fa/aprova | **2fa** | 30 | 0 | ID04+30 | ✅ |
| Empréstimo de R$ 2.000 ao amigo de sempre | legit | 2fa | **2fa** | 0 | 40 | TX04+40 | ✅ |
| Pix noturno de R$ 300 | legit | aprova | **aprova** | 0 | 25 | TX04+25 | ✅ |
| Pix noturno de R$ 1.500 (aluguel atrasado) | legit | 2fa | **2fa** | 0 | 5 | TX07+35, TR01-30 | ✅ |
| Primeiro Pix de cliente novo, R$ 150 | legit | 2fa/aprova | **aprova** | 10 | 0 | ID01+10 | ✅ |
| Viagem: SP pela manhã, Rio 6h depois | legit | aprova | **aprova** | 0 | 0 |  | ✅ |
| Falso parente: R$ 3.000 p/ conta de 2 dias | fraude | recusa | **recusa** | 0 | 75 | TX01+25, TX04+40, TX08+10 | ✅ |
| Falso parente: R$ 1.500 p/ conta de 5 dias | fraude | 2fa/recusa | **recusa** | 0 | 75 | TX01+25, TX04+40, TX08+10 | ✅ |
| Conta roubada: celular novo, R$ 5.000 p/ conta nova | fraude | recusa | **recusa** | 30 | 75 | ID01+30, ID02, TX01+25, TX04+40, TX08+10 | ✅ |
| Conta roubada: celular novo, internet banking, R$ 2.000 | fraude | 2fa/recusa | **recusa** | 40 | 50 | ID01+30, ID02, ID05+10, TX04+40, TX08+10 | ✅ |
| Esvaziamento: 4º Pix de R$ 1.500 no dia p/ destinos novos | fraude | 2fa/recusa | **2fa** | 0 | 35 | TX05+25, TX08+10 | ✅ |
| Conta laranja: 10º pagador/h, CPF de 3 dias | fraude | recusa | **recusa** | 0 | 65 | TX01+25, TX02+40 | ✅ |
| Conta laranja: CPF antigo, 10 pagadores/h | fraude | 2fa/recusa | **2fa** | 0 | 40 | TX02+40 | ✅ |
| Destino já barrado para 3 vítimas | fraude | 2fa/recusa | **recusa** | 0 | 80 | TX01+15, TX03+25, TX04+40 | ✅ |
| Fracionamento: 3º Pix de R$ 199 em 1h, celular novo | fraude | 2fa/recusa | **2fa** | 30 | 55 | ID01+30, TX04+25, TX06+30 | ✅ |
| Sequestro relâmpago: R$ 4.000 às 23h, aparelho de sempre | fraude | 2fa/recusa | **recusa** | 0 | 85 | TX04+40, TX07+35, TX08+10 | ✅ |
| Robô: 12º Pix em 10 min, celular novo | fraude | recusa | **recusa** | 80 | 0 | ID01+30, ID04+50 | ✅ |
| Viagem impossível + celular novo, R$ 1.000 | fraude | 2fa/recusa | **recusa** | 75 | 50 | ID01+30, ID02, ID03+45, TX04+40, TX08+10 | ✅ |
| Aquecimento: 3× R$ 1 em dias diferentes, depois R$ 5.000 | fraude | 2fa/recusa | **2fa** | 0 | 40 | TX04+40 | ✅ |
| Aquecimento: 3× R$ 600 em dias diferentes, depois R$ 2.500 | fraude | 2fa/recusa | **2fa** | 0 | 40 | TX01+15, TX04+25 | ✅ |

## Limiares alternativos

Mesmos cenários, mudando só um limiar por vez.

| Variação | Acertos | Legít. recusados | Legít. 2FA não previsto | Fraudes aprovadas | Fraudes só 2FA |
|---|---|---|---|---|---|
| Atual (2FA 30, recusa transação 60, identidade 80, ambos 40) | 30/30 | 0 | 0 | 0 | 5 |
| Recusa transação em 50 | 29/30 | 1 | 0 | 0 | 4 |
| Recusa transação em 70 | 29/30 | 0 | 0 | 0 | 6 |
| Recusa identidade em 70 | 30/30 | 0 | 0 | 0 | 5 |
| Recusa identidade em 90 | 29/30 | 0 | 0 | 0 | 6 |
| 2FA a partir de 25 | 29/30 | 0 | 1 | 0 | 5 |
| 2FA a partir de 35 | 30/30 | 0 | 0 | 0 | 5 |
| Sem a regra 'ambos ≥ 40' | 30/30 | 0 | 0 | 0 | 7 |
