from fastapi import FastAPI, Request

from database import clear_context, open_context


def register_session_manager_middleware(application: FastAPI) -> None:
    """Cuida do ciclo de vida da sessão de banco em cada requisição.

    O combinado, igual ao base-service:

    • rollback se a requisição terminou em exceção: nada fica pela metade;
    • close SEMPRE, no `finally`: conexão não devolvida é a próxima
      requisição esperando;
    • commit NUNCA. Quem sabe se o trabalho terminou é o controller: em
      src/controllers/pix_transaction_controller.py, o commit é a última
      linha antes do return, depois que tudo deu certo. O middleware cuida
      do ciclo de vida; o controller decide o conteúdo.

    A sessão pode não existir (rotas como /health_check não usam banco), e
    por isso todo rollback/close pergunta antes de agir. É o middleware mais
    interno da pilha, por isso é o primeiro registrado em src/app.py.
    """

    @application.middleware("http")
    async def manage_session(request: Request, call_next):
        context = open_context()

        try:
            response = await call_next(request)
        except Exception:
            if context.db_session is not None:
                context.db_session.rollback()
            raise
        finally:
            if context.db_session is not None:
                context.db_session.close()
            clear_context()

        return response
