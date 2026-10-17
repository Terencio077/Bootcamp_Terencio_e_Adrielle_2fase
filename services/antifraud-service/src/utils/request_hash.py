import hashlib
import json


def request_hash(payload: dict) -> str:
    """A impressão digital do corpo, para saber se a repetição é o mesmo pedido.

    sort_keys dá a mesma impressão ao mesmo pedido, seja qual for a ordem
    em que os campos vieram.
    """
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
