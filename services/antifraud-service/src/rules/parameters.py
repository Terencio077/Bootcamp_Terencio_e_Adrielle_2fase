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


RULES_VERSION = "2026.10.17"


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

    # ── ID01 Dispositivo novo ──────────────────────────────────────────
    new_device_points: int = 30
    # Primeiro Pix que o motor vê deste pagador: tudo é novo, inclusive o
    # aparelho. Pontua pouco para não punir o cliente pelo nosso cold start.
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
    velocity_window_minutes: int = 10
    velocity_two_factor_count: int = 5   # contando o Pix atual
    velocity_reject_count: int = 10      # contando o Pix atual
    velocity_points: int = 30

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

    # ── TX02 Conta laranja (muitos pagadores para o mesmo destino) ─────
    mule_window_minutes: int = 60
    mule_score_payers: int = 5           # pagadores distintos, contando o atual
    mule_reject_payers: int = 10
    mule_points: int = 40

    # ── TX03 Destino com recusas recentes ──────────────────────────────
    rejected_destination_days: int = 30
    rejected_destination_points: int = 25
    rejected_destination_many: int = 3
    rejected_destination_many_points: int = 45

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
    night_start_hour: int = 20
    night_end_hour: int = 6
    night_limit_cents: int = 100000
    night_points: int = 35

    # ── TX08 Primeira vez para este destino, valor relevante ───────────
    first_payment_amount_cents: int = 100000
    first_payment_points: int = 10

    # ── TR01/TR02 Confiança (descontam do eixo da transação) ───────────
    recurring_payee_min_count: int = 3
    recurring_payee_points: int = -30
    own_account_points: int = -20


DEFAULT_PARAMETERS = Parameters()
