# Resultado dos 28 testes adicionais

Execução em 17/10/2026, contra a v3 original.

24 passaram; 4 falharam; nenhum erro de preparação ou teste ignorado.

| Arquivo/grupo | Caso | Resultado |
|---|---|---|
| test_controller_adicional | `test_duplicidade_detectada_no_flush_devolve_analise_existente` | FALHOU |
| test_controller_adicional | `test_duplicidade_no_flush_com_corpo_diferente_gera_conflito` | FALHOU |
| test_controller_adicional | `test_duplicidade_detectada_no_commit_preserva_tratamento_existente` | PASSOU |
| test_controller_adicional | `test_data_sem_fuso_aponta_exatamente_o_campo_invalido[transaction_date]` | PASSOU |
| test_controller_adicional | `test_data_sem_fuso_aponta_exatamente_o_campo_invalido[source_account.opening_date]` | PASSOU |
| test_controller_adicional | `test_data_sem_fuso_aponta_exatamente_o_campo_invalido[destination_account.opening_date]` | PASSOU |
| test_controller_adicional | `test_falha_na_leitura_do_historico_nao_produz_decisao_falsa` | PASSOU |
| test_motor_adicional | `test_novo_id_apos_2fa_sem_confirmacao_continua_exigindo_desafio[apos_janela_de_rajada]` | PASSOU |
| test_motor_adicional | `test_novo_id_apos_2fa_sem_confirmacao_continua_exigindo_desafio[quase_uma_hora]` | PASSOU |
| test_motor_adicional | `test_pix_pequeno_nao_libera_aparelho_um_segundo_antes_de_24h` | PASSOU |
| test_motor_adicional | `test_comercio_com_35_pagadores_e_relacao_recorrente_aprova_compra_pequena` | PASSOU |
| test_motor_adicional | `test_mesmo_comercio_sem_relacao_recorrente_pede_confirmacao_sem_recusa` | PASSOU |
| test_motor_adicional | `test_cnpj_antigo_nao_ganha_imunidade_a_outros_sinais_fortes` | PASSOU |
| test_motor_adicional | `test_descontos_de_recorrencia_e_mesma_titularidade_nao_removem_piso_noturno` | PASSOU |
| test_motor_adicional | `test_fronteiras_da_janela_noturna[19:59:59-False]` | PASSOU |
| test_motor_adicional | `test_fronteiras_da_janela_noturna[20:00:00-True]` | PASSOU |
| test_motor_adicional | `test_fronteiras_da_janela_noturna[05:59:59-True]` | PASSOU |
| test_motor_adicional | `test_fronteiras_da_janela_noturna[06:00:00-False]` | PASSOU |
| test_motor_adicional | `test_desconto_nao_esconde_falha_da_regra_na_fronteira_de_valor[99999-TWO_FACTOR_REQUIRED]` | PASSOU |
| test_motor_adicional | `test_desconto_nao_esconde_falha_da_regra_na_fronteira_de_valor[100000-REJECTED]` | PASSOU |
| test_motor_adicional | `test_mesmo_instante_em_tres_offsets_nao_pode_fabricar_tres_dias_de_relacao` | FALHOU |
| test_tx03_consulta | `test_recusas_so_de_identidade_nao_contaminam_destino` | PASSOU |
| test_tx03_consulta | `test_recusa_que_precisou_dos_pontos_da_tx03_nao_se_reproduz` | PASSOU |
| test_tx03_consulta | `test_descontos_participam_do_calculo_sem_tx03` | PASSOU |
| test_tx03_consulta | `test_varias_recusas_do_mesmo_pagador_contam_uma_vez` | PASSOU |
| test_tx03_consulta | `test_so_entram_destino_janela_e_status_corretos` | PASSOU |
| test_tx03_consulta | `test_reject_da_propria_tx03_tambem_deve_ser_excluido_do_autorreforco` | FALHOU |
| test_tx03_consulta | `test_reject_de_outra_regra_transacional_continua_elegivel` | PASSOU |

As quatro falhas e as limitações de execução estão explicadas no README desta pasta.
