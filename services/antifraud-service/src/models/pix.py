from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class _DomainTable:
    """Tabela auxiliar de domínio: um valor novo é uma linha nova, sem mudar código."""

    id = Column(Integer, primary_key=True)
    enumerator = Column(String(50), nullable=False)


class AnalysisStatus(_DomainTable, Base):
    __tablename__ = "analysis_statuses"


class RiskAxis(_DomainTable, Base):
    __tablename__ = "risk_axes"


class PixTransaction(Base):
    __tablename__ = "pix_transactions"

    id = Column(Integer, primary_key=True)
    pix_id = Column(String(64), nullable=False)
    request_hash = Column(CHAR(64), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    utc_offset_minutes = Column(Integer, nullable=False)
    source_branch = Column(String(6), nullable=False)
    source_account_number = Column(String(20), nullable=False)
    source_opening_date = Column(DateTime(timezone=True), nullable=False)
    source_document = Column(String(14), nullable=False)
    destination_participant = Column(CHAR(8), nullable=False)
    destination_branch = Column(String(6), nullable=False)
    destination_account_number = Column(String(20), nullable=False)
    destination_opening_date = Column(DateTime(timezone=True), nullable=False)
    destination_document = Column(String(14), nullable=False)
    device_id = Column(String(128), nullable=False)
    channel = Column(String(32), nullable=False)
    ip = Column(String(45), nullable=False)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    received_at = Column(DateTime, nullable=False, server_default=func.now())


class PixAnalysis(Base):
    __tablename__ = "pix_analyses"

    id = Column(Integer, primary_key=True)
    analysis_key = Column(CHAR(36), nullable=False)
    pix_transaction_id = Column(Integer, ForeignKey("pix_transactions.id"), nullable=False)
    analysis_status_id = Column(Integer, ForeignKey("analysis_statuses.id"), nullable=False)
    identity_score = Column(Integer, nullable=False)
    transaction_score = Column(Integer, nullable=False)
    decision_reason = Column(String(500), nullable=False)
    rules_version = Column(String(20), nullable=False)
    latency_ms = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class RuleHit(Base):
    __tablename__ = "rule_hits"

    id = Column(Integer, primary_key=True)
    pix_analysis_id = Column(Integer, ForeignKey("pix_analyses.id"), nullable=False)
    rule_code = Column(String(10), nullable=False)
    risk_axis_id = Column(Integer, ForeignKey("risk_axes.id"), nullable=False)
    effect = Column(String(20), nullable=False)
    points = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    evidence = Column(JSONB, nullable=False)
