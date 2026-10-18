from models import PixAnalysis, PixTransaction


def analysis_to_dict(transaction: PixTransaction, analysis: PixAnalysis, status: str, hits: list) -> dict:
    return {
        "key": analysis.analysis_key,
        "status": status.lower(),
        "metadata": {
            "pix_id": transaction.pix_id,
            "decision_reason": analysis.decision_reason,
            "scores": {
                "identity": analysis.identity_score,
                "transaction": analysis.transaction_score,
            },
            "rules_triggered": [
                {
                    "rule": hit.rule_code,
                    "axis": axis.lower(),
                    "effect": hit.effect.lower(),
                    "points": hit.points,
                    "reason": hit.reason,
                    "evidence": hit.evidence,
                }
                for hit, axis in hits
            ],
            "rules_version": analysis.rules_version,
            "decision_latency_ms": float(analysis.latency_ms),
            "analysed_at": analysis.created_at.isoformat() if analysis.created_at else None,
        },
    }
