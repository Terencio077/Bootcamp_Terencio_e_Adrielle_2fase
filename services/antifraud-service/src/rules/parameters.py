"""Todos os números do motor, num lugar só.

Por que um arquivo só de números: a QI Tech contou que recalibra as regras
toda semana. Calibrar é mexer AQUI, e não caçar um `if valor > 20000`
perdido no meio de uma regra. Cada análise grava a RULES_VERSION com que
foi decidida, então uma decisão antiga continua explicável depois que os
números mudarem.

O porquê de cada número está no README, na tabela de regras. Os
comentários aqui dizem só de onde ele veio.

Dinheiro é sempre centavos em inteiro (R$ 200,00 = 20000), como no
contrato da API e no projeto da primeira etapa.
"""

from dataclasses import dataclass


RULES_VERSION = "2026.10.17-r5"


@dataclass(frozen=True)
class Parameters:
    # ── Decisão (como as notas viram status) ───────────────────────────
    # A dúvida começa no mesmo ponto nos dois eixos...
    two_factor_threshold: int = 30
    # ...mas a recusa é ASSIMÉTRICA. O 2FA prova QUEM está pagando; ele não
    # prova que a transação é legítima (no golpe, o dono da conta passa no
    # 2FA e paga o golpista assim mesmo). Por isso o eixo da transação
    # recusa mais cedo: ali, pedir 2FA protege menos.
    transaction_reject_threshold: int = 60
    identity_reject_threshold: int = 80
    # Dúvida séria sobre quem E sobre o quê ao mesmo tempo: o retrato do
    # roubo de conta (aparelho estranho mandando dinheiro para conta nova).
    both_axes_reject_threshold: int = 40

    # ── Janelas de histórico ───────────────────────────────────────────
    history_days: int = 90
    history_max_rows: int = 500

    # ── Confiança do aparelho (usada por ID01 e ID02) ──────────────────
    # Confiável = tem um Pix APROVADO a partir dele há pelo menos 24 h. As
    # 24 h impedem que um Pix pequeno aprovado libere, minutos depois, um
    # Pix grande no mesmo aparelho. Nada além de aprovação confirma um
    # aparelho: tentativa pendente (2FA) ou recusada nunca vira confirmação.
    device_trust_min_age_hours: int = 24
    # Uso recorrente (HIPÓTESE a calibrar): aparelho visto em pelo menos 3
    # dias diferentes, ao longo de pelo menos 7 dias, sem nenhuma recusa.
    # NÃO confirma o aparelho; só reduz a suspeita da ID01. Indica histórico
    # de uso, não identidade comprovada.
    device_recurring_min_days: int = 3
    device_recurring_min_age_days: int = 7

    # ── ID01 Dispositivo não confiável ─────────────────────────────────
    new_device_points: int = 30          # pagador tem outro aparelho confiável: troca de aparelho
    recurring_device_points: int = 15    # aparelho em uso recorrente, ainda sem aprovação
    # Pagador ainda sem nenhum aparelho confiável: tudo é novo para o motor.
    # Pontua pouco para não punir o cliente pelo nosso cold start.
    first_seen_payer_device_points: int = 10

    # ── ID02 Limite de dispositivo não cadastrado (regulação) ──────────
    # Valores citados na apresentação: dispositivo não cadastrado opera até
    # R$ 200 por Pix e R$ 1.000 por dia.
    untrusted_device_max_per_pix_cents: int = 20000
    untrusted_device_max_per_day_cents: int = 100000

    # ── ID03 Viagem impossível ─────────────────────────────────────────
    impossible_travel_speed_kmh: float = 900.0     # avião comercial
    impossible_travel_min_distance_km: float = 100.0  # abaixo disso, ruído de GPS/IP
    impossible_travel_points: int = 45

    # ── ID04 Rajada (velocity) ─────────────────────────────────────────
    # Sem bloqueio isolado: dividir a conta do churrasco com dez amigos é
    # legítimo. Pede 2FA (que também barra automação); recusa só somada.
    velocity_window_minutes: int = 10
    velocity_count: int = 5              # contando o Pix atual
    velocity_points: int = 30
    velocity_high_count: int = 10
    velocity_high_points: int = 50

    # ── ID05 Canal novo ────────────────────────────────────────────────
    new_channel_min_history: int = 5
    new_channel_points: int = 10

    # ── ID06 Madrugada fora do hábito ──────────────────────────────────
    dawn_start_hour: int = 0
    dawn_end_hour: int = 5               # inclusive
    dawn_min_history: int = 10
    dawn_points: int = 15

    # ── TX01 Conta de destino recém-aberta ─────────────────────────────
    young_destination_days: int = 7
    young_destination_points: int = 25
    recent_destination_days: int = 30
    recent_destination_points: int = 15

    # ── TX02 Concentração de pagadores ─────────────────────────────────
    # Pagadores distintos (contando o atual) que TENTARAM pagar a mesma
    # conta na janela. Sem bloqueio isolado: o tipo do recebedor
    # contextualiza (um comércio recebe de muita gente; uma pessoa física,
    # raramente) e a idade da conta já pesa na TX01, somando a esta.
    concentration_window_minutes: int = 60
    concentration_person_payers: int = 5
    concentration_person_points: int = 25
    concentration_person_high_payers: int = 10
    concentration_person_high_points: int = 40
    concentration_company_payers: int = 15
    concentration_company_points: int = 15
    concentration_company_high_payers: int = 30
    concentration_company_high_points: int = 30
    # Padrão da própria conta: só conta o que passa de 1,5× o maior
    # movimento (pagadores distintos numa hora) que ela teve nos últimos
    # 30 dias. O restaurante que sempre lota no almoço não pontua; a conta
    # que recebia ninguém e de repente recebe dez, pontua inteira.
    concentration_own_peak_days: int = 30
    concentration_own_peak_factor: float = 1.5

    # ── TX03 Destino com recusas recentes ──────────────────────────────
    # Só contam recusas causadas pelo lado da transação (nota da transação
    # sem a própria TX03 >= transaction_reject_threshold, ou bloqueio de
    # regra de transação), de pagadores DIFERENTES. Peso limitado: a regra
    # não pode se alimentar das próprias decisões.
    rejected_destination_days: int = 30
    rejected_destination_min_payers: int = 2
    rejected_destination_points: int = 25

    # ── TX04 Valor fora do perfil ──────────────────────────────────────
    profile_min_history: int = 5
    profile_high_factor: float = 2.0
    profile_high_points: int = 25
    profile_extreme_factor: float = 5.0
    profile_extreme_points: int = 40
    # Sem histórico suficiente não há perfil para comparar; só um valor
    # alto pesa, e pouco.
    no_profile_high_amount_cents: int = 500000
    no_profile_high_amount_points: int = 15

    # ── TX05 Soma do dia fora do padrão ────────────────────────────────
    daily_sum_min_history_days: int = 7
    daily_sum_factor: float = 3.0
    daily_sum_floor_cents: int = 200000
    daily_sum_points: int = 25

    # ── TX06 Fracionamento (vários Pix logo abaixo de um limite) ───────
    structuring_window_minutes: int = 60
    structuring_band_ratio: float = 0.90   # entre 90% e 100% do limite
    structuring_min_count: int = 3         # contando o atual
    structuring_points: int = 30

    # ── TX07 Limite noturno (regulação, pessoa física) ─────────────────
    # HIPÓTESE: o contrato não informa o limite nem o horário que o cliente
    # configurou (ele pode mudar para 22h-6h e pedir aumento). Assumimos o
    # padrão e, acima dele, exigimos confirmação (piso de 2FA que a
    # confiança não derruba) em vez de recusar um limite que talvez tenha
    # sido elevado.
    night_start_hour: int = 20
    night_end_hour: int = 6
    night_limit_cents: int = 100000
    night_points: int = 35

    # ── TX08 Primeira vez para este destino, valor relevante ───────────
    first_payment_amount_cents: int = 100000
    first_payment_points: int = 10

    # ── Falha de regra ─────────────────────────────────────────────────
    # Regra de identidade que falha: 2FA resolve a dúvida. Regra de
    # transação que falha: o 2FA não resolve; recusa a partir deste valor
    # (dano potencial alto) e pede 2FA abaixo dele.
    rule_error_reject_amount_cents: int = 100000

    # ── TR01/TR02 Confiança (descontam do eixo da transação) ───────────
    # Recorrência = Pix APROVADOS para o mesmo recebedor em dias
    # DIFERENTES. Três Pix na mesma tarde não são recorrência: é o
    # "aquecimento" que um fraudador faria antes do Pix grande.
    recurring_payee_min_count: int = 3
    # Materialidade (decisão do time): um relacionamento pequeno não avaliza
    # um valor muito maior. Acima de 5x o MAIOR Pix aprovado para este
    # recebedor, o desconto não vale. É a mesma régua do TX04 (acima de 5x o
    # maior Pix já feito = valor extremo), para o motor inteiro falar a mesma
    # língua. Escolhido comparando casos montados pelo time (README).
    recurring_payee_max_ratio: float = 5.0
    # Tempo de relacionamento (decisão do time): o primeiro Pix aprovado para
    # o recebedor tem de ter pelo menos 30 dias. É o ciclo de uma conta mensal
    # (aluguel, luz, escola): um relacionamento real atravessa ao menos um.
    # Três Pix em três dias seguidos não são relacionamento, são aquecimento.
    recurring_payee_min_age_days: int = 30
    recurring_payee_points: int = -30
    own_account_points: int = -20


DEFAULT_PARAMETERS = Parameters()
