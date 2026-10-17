from datetime import timedelta, timezone

from sqlalchemy import func, text

from database import Context
from models import AnalysisStatus, PixAnalysis, PixTransaction
from rules import DestinationHistory, History, Parameters, PastPix, PixRequest


class HistoryRepository:
    """Monta o passado que o motor precisa, em TRÊS consultas por Pix.

    O orçamento de tempo de um Pix é de poucos segundos para a cadeia
    inteira, e o antifraude é só um elo dela. Por isso o histórico não é
    consultado regra a regra: ele vem de uma vez, antes das regras, e cada
    consulta anda num índice criado para ela (ver database/database.sql).

    1. O passado do PAGADOR (até 500 Pix dos últimos 90 dias). Quase todas
       as regras saem desta lista: rajada, aparelho, perfil, noite, soma do
       dia, geolocalização, recorrência.
    2. Quantos pagadores DIFERENTES tentaram pagar o destino na última hora.
    3. Quantos pagadores diferentes tiveram Pix para o destino recusado no
       último mês POR RISCO DA TRANSAÇÃO (ver rejected_destination_payers).

    O "agora" das consultas é a transaction_date do Pix, nunca o NOW() do
    banco: o histórico de um Pix é o que aconteceu antes DELE.

    O LIMITE DE 500: só corta quem faz mais de 500 Pix em 90 dias. As
    janelas curtas (10 min, 24 h, a noite) continuam completas; a de 30 dias
    pode ficar parcial, e aí a média diária sai menor e o motor pede MAIS
    confirmação, não menos. Calcular esses agregados no banco é o próximo
    passo se o perfil de clientes tiver muitos pagadores intensos (empresas).
    """

    def lock_participants(self, pix: PixRequest) -> None:
        """Serializa análises simultâneas do mesmo pagador ou do mesmo destino.

        Sem isto, dois Pix do mesmo pagador chegando juntos leem o histórico
        antes de qualquer um gravar, e a rajada (ou a soma do dia) conta um a
        menos para cada um. A trava é do próprio Postgres (advisory lock de
        transação): sai sozinha no commit ou no rollback.

        As duas chaves são travadas SEMPRE na mesma ordem (ordenadas), pelo
        mesmo motivo das travas ordenadas da primeira etapa: A pagando B e B
        pagando A ao mesmo tempo esperam uma pela outra em fila, em vez de
        travarem para sempre (deadlock).
        """
        participant, branch, account_number = pix.destination_account
        keys = sorted({f"payer:{pix.source_document}", f"destination:{participant}:{branch}:{account_number}"})
        for key in keys:
            self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

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

        concentration_since = pix.transaction_date - timedelta(minutes=parameters.concentration_window_minutes)
        other_payers = (
            self.session.query(func.count(func.distinct(PixTransaction.source_document)))
            .filter(*same_destination,
                    PixTransaction.transaction_date >= concentration_since,
                    PixTransaction.source_document != pix.source_document)
            .scalar()
        )

        rejected_payers = self.rejected_destination_payers(pix, parameters)

        return DestinationHistory(distinct_other_payers_in_window=other_payers or 0,
                                  rejected_payers_in_window=rejected_payers)

    def rejected_destination_payers(self, pix: PixRequest, parameters: Parameters) -> int:
        """Pagadores distintos cujo Pix para este destino foi recusado por risco DA TRANSAÇÃO.

        Uma recusa só conta se ela se sustentava pelo lado da transação SEM a
        própria TX03: a soma dos pontos das regras de transação, tirando a
        TX03, chegou ao limite de recusa — ou OUTRA regra de transação recusou
        sozinha (efeito REJECT). Ficam de fora:
        • recusas causadas pelo pagador (viagem impossível, rajada);
        • qualquer contribuição da própria TX03, nos pontos E no bloqueio, para
          ela não se alimentar das próprias decisões;
        • recusas por falha técnica (FAILSAFE_*): um defeito nosso não é
          evidência de fraude do recebedor.
        """
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
