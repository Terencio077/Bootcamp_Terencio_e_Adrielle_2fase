"""Experimentos de política, sem assert de certo/errado.

Execute da raiz: python testes_revisao_v3/explorar_politicas.py
Os resultados mostram riscos a discutir; aprovação não prova fraude real.
"""

import json
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "antifraud-service" / "src"))

from casos import NOW, history, past, pix, usual
from rules import DecisionEngine


def describe(decision):
    return {"status": decision.status, "identity": decision.identity_score,
            "transaction": decision.transaction_score,
            "rules": [{"code": hit.code, "points": hit.points, "effect": hit.effect}
                      for hit in decision.hits]}


def main():
    engine = DecisionEngine()
    first_pix = pix(amount_cents=5000)
    first = engine.evaluate(first_pix, history())
    seed = past(transaction_date=NOW, amount_cents=5000, status=first.status)
    second = engine.evaluate(
        replace(first_pix, pix_id="after-24h", amount_cents=50000,
                transaction_date=NOW + timedelta(hours=24, seconds=1)), history(seed),
    )

    target = "55566677788"
    target_account = ("60701190", "3675", "99001")
    base = usual()
    warming = []
    for day in (3, 2, 1):
        request = pix(pix_id=f"warming-{day}", amount_cents=100,
                      transaction_date=NOW - timedelta(days=day),
                      destination_document=target, destination_account=target_account)
        available = [item for item in base if item.transaction_date <= request.transaction_date]
        result = engine.evaluate(request, history(*available))
        warming.append(describe(result))
        base.append(past(transaction_date=request.transaction_date, amount_cents=100,
                         destination_document=target, destination_account=target_account,
                         status=result.status))
    large = engine.evaluate(
        pix(amount_cents=500000, destination_document=target, destination_account=target_account),
        history(*base),
    )
    print(json.dumps({
        "device_50_then_500_after_24h": {"seed": describe(first), "followup": describe(second)},
        "three_pix_of_1_on_distinct_days_then_5000": {"seeds": warming, "followup": describe(large)},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
