from dataclasses import dataclass


RULES_VERSION = "2026.10.17-r6"


@dataclass(frozen=True)
class Parameters:
    two_factor_threshold: int = 30
    transaction_reject_threshold: int = 60
    identity_reject_threshold: int = 80
    both_axes_reject_threshold: int = 40

    history_days: int = 90
    history_max_rows: int = 500

    device_trust_min_age_hours: int = 24
    device_recurring_min_days: int = 3
    device_recurring_min_age_days: int = 7

    new_device_points: int = 30
    recurring_device_points: int = 15
    first_seen_payer_device_points: int = 10

    untrusted_device_max_per_pix_cents: int = 20000
    untrusted_device_max_per_day_cents: int = 100000

    impossible_travel_speed_kmh: float = 900.0
    impossible_travel_min_distance_km: float = 100.0
    impossible_travel_points: int = 45

    velocity_window_minutes: int = 10
    velocity_count: int = 5
    velocity_points: int = 30
    velocity_high_count: int = 10
    velocity_high_points: int = 50

    new_channel_min_history: int = 5
    new_channel_points: int = 10

    dawn_start_hour: int = 0
    dawn_end_hour: int = 5
    dawn_min_history: int = 10
    dawn_points: int = 15

    young_destination_days: int = 7
    young_destination_points: int = 25
    recent_destination_days: int = 30
    recent_destination_points: int = 15

    concentration_window_minutes: int = 60
    concentration_person_payers: int = 5
    concentration_person_points: int = 25
    concentration_person_high_payers: int = 10
    concentration_person_high_points: int = 40
    concentration_company_payers: int = 15
    concentration_company_points: int = 15
    concentration_company_high_payers: int = 30
    concentration_company_high_points: int = 30
    concentration_own_peak_days: int = 30
    concentration_own_peak_factor: float = 1.5

    rejected_destination_days: int = 30
    rejected_destination_min_payers: int = 2
    rejected_destination_points: int = 25

    profile_min_history: int = 5
    profile_high_factor: float = 2.0
    profile_high_points: int = 25
    profile_extreme_factor: float = 5.0
    profile_extreme_points: int = 40
    no_profile_high_amount_cents: int = 500000
    no_profile_high_amount_points: int = 15

    daily_sum_min_history_days: int = 7
    daily_sum_factor: float = 3.0
    daily_sum_floor_cents: int = 200000
    daily_sum_points: int = 25

    structuring_window_minutes: int = 60
    structuring_band_ratio: float = 0.90
    structuring_min_count: int = 3
    structuring_points: int = 30

    night_start_hour: int = 20
    night_end_hour: int = 6
    night_limit_cents: int = 100000
    night_points: int = 35

    first_payment_amount_cents: int = 100000
    first_payment_points: int = 10

    payer_lock_timeout_ms: int = 500

    rule_error_reject_amount_cents: int = 100000

    recurring_payee_min_count: int = 3
    recurring_payee_max_ratio: float = 5.0
    recurring_payee_min_age_days: int = 30
    recurring_payee_points: int = -30
    own_account_points: int = -20


DEFAULT_PARAMETERS = Parameters()
