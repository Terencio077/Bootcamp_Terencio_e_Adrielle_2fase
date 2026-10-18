from typing import Optional
from uuid import uuid4

from database import Context
from models import AnalysisStatus, PixAnalysis, PixTransaction, RiskAxis, RuleHit
from rules import Decision, PixRequest


class PixRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self._domain_ids = {}

    def domain_id(self, model, enumerator: str) -> int:
        cache_key = (model.__tablename__, enumerator)
        if cache_key not in self._domain_ids:
            self._domain_ids[cache_key] = self.session.query(model.id).filter(
                model.enumerator == enumerator).scalar()
        return self._domain_ids[cache_key]

    def find_transaction(self, pix_id: str) -> Optional[PixTransaction]:
        return self.session.query(PixTransaction).filter(PixTransaction.pix_id == pix_id).first()

    def find_analysis(self, pix_id: str) -> Optional[tuple]:
        row = (
            self.session.query(PixTransaction, PixAnalysis, AnalysisStatus.enumerator)
            .join(PixAnalysis, PixAnalysis.pix_transaction_id == PixTransaction.id)
            .join(AnalysisStatus, AnalysisStatus.id == PixAnalysis.analysis_status_id)
            .filter(PixTransaction.pix_id == pix_id)
            .first()
        )
        if row is None:
            return None

        transaction, analysis, status = row
        hits = (
            self.session.query(RuleHit, RiskAxis.enumerator)
            .join(RiskAxis, RiskAxis.id == RuleHit.risk_axis_id)
            .filter(RuleHit.pix_analysis_id == analysis.id)
            .order_by(RuleHit.id)
            .all()
        )
        return transaction, analysis, status, hits

    def save(self, payload: dict, pix: PixRequest, request_hash: str, decision: Decision,
             latency_ms: float) -> None:
        transaction = PixTransaction()
        transaction.pix_id = pix.pix_id
        transaction.request_hash = request_hash
        transaction.amount_cents = pix.amount_cents
        transaction.transaction_date = pix.transaction_date
        transaction.utc_offset_minutes = int(pix.transaction_date.utcoffset().total_seconds() // 60)
        transaction.source_branch = payload["source_account"]["branch"]
        transaction.source_account_number = payload["source_account"]["account_number"]
        transaction.source_opening_date = pix.source_opening_date
        transaction.source_document = pix.source_document
        transaction.destination_participant, transaction.destination_branch, \
            transaction.destination_account_number = pix.destination_account
        transaction.destination_opening_date = pix.destination_opening_date
        transaction.destination_document = pix.destination_document
        transaction.device_id = pix.device_id
        transaction.channel = pix.channel
        transaction.ip = pix.ip
        transaction.latitude = pix.latitude
        transaction.longitude = pix.longitude
        self.session.add(transaction)
        self.session.flush()

        analysis = PixAnalysis()
        analysis.analysis_key = str(uuid4())
        analysis.pix_transaction_id = transaction.id
        analysis.analysis_status_id = self.domain_id(AnalysisStatus, decision.status)
        analysis.identity_score = decision.identity_score
        analysis.transaction_score = decision.transaction_score
        analysis.decision_reason = decision.reason[:500]
        analysis.rules_version = decision.rules_version
        analysis.latency_ms = round(latency_ms, 2)
        self.session.add(analysis)
        self.session.flush()

        for hit in decision.hits:
            rule_hit = RuleHit()
            rule_hit.pix_analysis_id = analysis.id
            rule_hit.rule_code = hit.code
            rule_hit.risk_axis_id = self.domain_id(RiskAxis, hit.axis)
            rule_hit.effect = hit.effect
            rule_hit.points = hit.points
            rule_hit.reason = hit.reason[:500]
            rule_hit.evidence = hit.evidence
            self.session.add(rule_hit)
