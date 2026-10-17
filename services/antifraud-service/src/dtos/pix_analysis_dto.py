from models import PixAnalysis, PixTransaction


def analysis_to_dict(transaction: PixTransaction, analysis: PixAnalysis, status: str, hits: list) -> dict:
    """A análise como o contrato pede: key, status e metadata.

    O metadata é livre no contrato, e aqui ele é o dossiê da decisão: o
    suficiente para o atendimento responder "por que meu Pix foi
    bloqueado?" sem abrir o banco. Nenhum id interno sai — só a key da
    análise e o id do Pix, que foi quem chamou que escolheu.

    O POST e o GET devolvem exatamente este formato: o GET é a mesma
    análise, relida do banco.
    """
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
