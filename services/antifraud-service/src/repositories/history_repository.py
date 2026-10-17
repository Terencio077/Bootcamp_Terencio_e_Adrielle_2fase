from datetime import timedelta, timezone

from sqlalchemy import func

from database import Context
from models import AnalysisStatus, PixAnalysis, PixTransaction
from rules import DestinationHistory, History, Parameters, PastPix, PixRequest


class HistoryRepository:
    """Monta o passado que o motor precisa, em DUAS consultas por Pix.

    O orçamento de tempo de um Pix é de poucos segundos para a cadeia
    inteira, e o antifraude é só um elo dela. Por isso o histórico não é
    consultado regra a regra: ele vem de uma vez, antes das regras, e cada
    consulta anda num índice criado para ela (ver database/database.sql).

    1. O passado do PAGADOR (até 500 Pix dos últimos 90 dias). Quase todas
       as regras saem desta lista: rajada, aparelho, perfil, noite, soma do
       dia, geolocalização, recorrência.
    2. O passado do DESTINO, já agregado no banco: quantos pagadores
       diferentes mandaram para ele na última hora e quantos Pix para ele
       foram recusados no último mês.

    O "agora" das consultas é a transaction_date do Pix, nunca o NOW() do
    banco: o histórico de um Pix é o que aconteceu antes DELE.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def load(self, pix: PixRequest, parameters: Parameters) -> History:
        return History(
            payer_pix=self.payer_history(pix, parameters),
            destination=self.destination_history(pix, parameters),
        )

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

        mule_since = pix.transaction_date - timedelta(minutes=parameters.mule_window_minutes)
        other_payers = (
            self.session.query(func.count(func.distinct(PixTransaction.source_document)))
            .filter(*same_destination,
                    PixTransaction.transaction_date >= mule_since,
                    PixTransaction.source_document != pix.source_document)
            .scalar()
        )

        rejected_since = pix.transaction_date - timedelta(days=parameters.rejected_destination_days)
        rejected = (
            self.session.query(func.count(PixTransaction.id))
            .join(PixAnalysis, PixAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == PixAnalysis.analysis_status_id)
            .filter(*same_destination,
                    PixTransaction.transaction_date >= rejected_since,
                    AnalysisStatus.enumerator == "REJECTED")
            .scalar()
        )

        return DestinationHistory(distinct_other_payers_in_window=other_payers or 0,
                                  rejected_in_window=rejected or 0)


def to_past_pix(transaction: PixTransaction, status: str) -> PastPix:
    # O banco devolve o instante em UTC; as regras de horário (noite,
    # madrugada) precisam da hora no relógio de quem pagou, então o fuso
    # original volta a ser aplicado aqui.
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
