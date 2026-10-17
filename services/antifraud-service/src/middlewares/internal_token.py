import hmac

from fastapi import FastAPI, Request

from constants import BYPASS_ENDPOINTS, INTERNAL_TOKEN
from errors.base_error import ForbiddenNotInternal
from errors.handlers import qi_exception_to_response


def register_internal_token_middleware(application: FastAPI) -> None:
    """Deixa passar só quem manda o header INTERNAL-TOKEN com o valor certo.

    O valor certo vem da variável de ambiente INTERNAL_TOKEN, nunca do
    código. As rotas de BYPASS_ENDPOINTS (raiz e health check) são públicas.

    Repare que aqui a gente DEVOLVE a resposta de erro em vez de levantar
    a exceção: dentro de um middleware, ninguém está escutando pra traduzir
    o erro — quem traduz são os exception handlers, que rodam mais pra
    dentro. Levantar aqui viraria um 500.

    A comparação usa hmac.compare_digest, que leva o mesmo tempo dê o
    token certo ou errado: com `!=`, a resposta sai um pouco mais rápido
    quando o primeiro caractere já difere, e isso pode vazar o segredo aos
    poucos para quem mede o tempo de muitas tentativas.
    """

    @application.middleware("http")
    async def check_internal_token(request: Request, call_next):
        is_public = request.url.path in BYPASS_ENDPOINTS

        if request.method == "OPTIONS" or is_public:
            return await call_next(request)

        received = request.headers.get("INTERNAL-TOKEN") or ""
        if not hmac.compare_digest(received.encode(), INTERNAL_TOKEN.encode()):
            return qi_exception_to_response(ForbiddenNotInternal())

        return await call_next(request)
