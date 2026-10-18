from datetime import timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError

from database import Context
from models import AnalysisStatus, PixAnalysis, PixTransaction
from rules import DestinationHistory, History, Parameters, PastPix, PixRequest


class HistoryRepository:

    def lock_participants(self, pix: PixRequest, timeout_ms: int) -> bool:
        savepoint = self.session.begin_nested()
        try:
            self.session.execute(text(f"SET LOCAL lock_timeout = '{int(timeout_ms)}ms'"))
            self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                                 {"key": f"payer:{pix.source_document}"})
            self.session.execute(text("SET LOCAL lock_timeout = 0"))
            savepoint.commit()
            return True
        except OperationalError as error:
            if getattr(error.orig, "pgcode", None) != "55P03":
                raise
            savepoint.rollback()
            return False

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def load(self, pix: PixRequest, parameters: Parameters, payer_lock_timed_out: bool = False) -> History:
        first_seen, baseline = self.payer_aggregates(pix)
        return History(
            payer_pix=self.payer_history(pix, parameters),
            destination=self.destination_history(pix, parameters),
            payer_first_seen=first_seen,
            payer_baseline_30d_cents=baseline,
            payer_lock_timed_out=payer_lock_timed_out,
        )

    def payer_aggregates(self, pix: PixRequest) -> tuple:
        result = self.session.execute(text("""
            SELECT MIN(t.transaction_date),
                   COALESCE(SUM(t.amount_cents) FILTER (
                       WHERE t.transaction_date >= :baseline_start AND t.transaction_date < :day_start
                         AND s.enumerator IN ('APPROVED', 'TWO_FACTOR_REQUIRED')), 0)
            FROM pix_transactions t
            JOIN pix_analyses a ON a.pix_transaction_id = t.id
            JOIN analysis_statuses s ON s.id = a.analysis_status_id
            WHERE t.source_document = :payer AND t.transaction_date <= :now AND t.pix_id <> :pix_id
        """), {"payer": pix.source_document, "now": pix.transaction_date, "pix_id": pix.pix_id,
               "baseline_start": pix.transaction_date - timedelta(days=30),
               "day_start": pix.transaction_date - timedelta(hours=24)}).first()
        if result is None or result[0] is None:
            return None, None
        return result[0], int(result[1])

    def payer_history(self, pix: PixRequest, parameters: Parameters) -> list:
        since = pix.transaction_date - timedelta(days=parameters.history_days)
        rows = (
            self.session.query(PixTransaction, AnalysisStatus.enumerator)
            .join(PixAnalysis, PixAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == PixAnalysis.analysis_status_id)
            .filter(
                PixTransaction.source_document == pix.source_document,
                PixTransaction.transaction_date >= since,
                PixTransaction.transaction_date <= pix.transaction_date,
                PixTransaction.pix_id != pix.pix_id,
            )
            .order_by(PixTransaction.transaction_date.desc(), PixTransaction.id.desc())
            .limit(parameters.history_max_rows)
            .all()
        )
        return [to_past_pix(transaction, status) for transaction, status in rows]

    def destination_history(self, pix: PixRequest, parameters: Parameters) -> DestinationHistory:
        participant, branch, account_number = pix.destination_account
        same_destination = [
            PixTransaction.destination_participant == participant,
            PixTransaction.destination_branch == branch,
            PixTransaction.destination_account_number == account_number,
            PixTransaction.transaction_date <= pix.transaction_date,
            PixTransaction.pix_id != pix.pix_id,
        ]

        concentration_since = pix.transaction_date - timedelta(minutes=parameters.concentration_window_minutes)
        other_payers = (
            self.session.query(func.count(func.distinct(PixTransaction.source_document)))
            .filter(*same_destination,
                    PixTransaction.transaction_date >= concentration_since,
                    PixTransaction.source_document != pix.source_document)
            .scalar()
        )

        rejected_payers = self.rejected_destination_payers(pix, parameters)

        peak = self.session.execute(text("""
            SELECT COALESCE(MAX(n), 0) FROM (
                SELECT COUNT(DISTINCT source_document) AS n
                FROM pix_transactions
                WHERE destination_participant = :participant AND destination_branch = :branch
                  AND destination_account_number = :account
                  AND transaction_date >= :since AND transaction_date < :window_start
                GROUP BY date_trunc('hour', transaction_date)
            ) per_hour
        """), {"participant": participant, "branch": branch, "account": account_number,
               "since": pix.transaction_date - timedelta(days=parameters.concentration_own_peak_days),
               "window_start": concentration_since}).scalar()

        return DestinationHistory(distinct_other_payers_in_window=other_payers or 0,
                                  rejected_payers_in_window=rejected_payers,
                                  peak_payers_30d=int(peak or 0))

    def rejected_destination_payers(self, pix: PixRequest, parameters: Parameters) -> int:
        participant, branch, account_number = pix.destination_account
        query = text("""
            SELECT COUNT(DISTINCT t.source_document)
            FROM pix_transactions t
            JOIN pix_analyses a ON a.pix_transaction_id = t.id
            JOIN analysis_statuses s ON s.id = a.analysis_status_id
            WHERE s.enumerator = 'REJECTED'
              AND t.destination_participant = :participant
              AND t.destination_branch = :branch
              AND t.destination_account_number = :account_number
              AND t.transaction_date >= :since
              AND t.transaction_date <= :now
              AND t.pix_id <> :pix_id
              AND (
                (SELECT COALESCE(SUM(h.points), 0)
                   FROM rule_hits h JOIN risk_axes x ON x.id = h.risk_axis_id
                  WHERE h.pix_analysis_id = a.id AND x.enumerator = 'TRANSACTION' AND h.rule_code <> 'TX03')
                  >= :reject_threshold
                OR EXISTS (SELECT 1
                             FROM rule_hits h JOIN risk_axes x ON x.id = h.risk_axis_id
                            WHERE h.pix_analysis_id = a.id AND x.enumerator = 'TRANSACTION'
                              AND h.effect = 'REJECT' AND h.rule_code <> 'TX03')
              )
        """)
        result = self.session.execute(query, {
            "participant": participant,
            "branch": branch,
            "account_number": account_number,
            "since": pix.transaction_date - timedelta(days=parameters.rejected_destination_days),
            "now": pix.transaction_date,
            "pix_id": pix.pix_id,
            "reject_threshold": parameters.transaction_reject_threshold,
        }).scalar()
        return result or 0


def to_past_pix(transaction: PixTransaction, status: str) -> PastPix:
    local_zone = timezone(timedelta(minutes=transaction.utc_offset_minutes))
    return PastPix(
        transaction_date=transaction.transaction_date.astimezone(local_zone),
        amount_cents=transaction.amount_cents,
        status=status,
        device_id=transaction.device_id,
        channel=transaction.channel,
        destination_account=(transaction.destination_participant, transaction.destination_branch,
                             transaction.destination_account_number),
        destination_document=transaction.destination_document,
        latitude=float(transaction.latitude) if transaction.latitude is not None else None,
        longitude=float(transaction.longitude) if transaction.longitude is not None else None,
    )
