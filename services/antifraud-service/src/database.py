"""Onde a sessão de banco mora, e como ela chega em quem precisa dela.

Mesmo desenho do base-service: o middleware src/middlewares/session_manager.py
abre um contexto vazio no começo de cada requisição e o fecha no fim; quem
cria a sessão, se precisar, é o controller (BaseController), pedindo ao
contexto. O contexto viaja num `contextvars`, o mesmo mecanismo do
identificador da requisição em src/utils/request_context.py.

Duas consequências que valem saber:

• A sessão é preguiçosa: `/` e `/health_check` não constroem controller,
  então não dependem do banco estar de pé.
• Só o controller chama `get_context()`. A sessão está "no ar" e qualquer
  camada conseguiria alcançá-la; o combinado é que não alcança.
"""

from contextvars import ContextVar
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from constants import DATABASE_URL


engine = create_engine(DATABASE_URL, pool_size=5, pool_recycle=600, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Context:
    """O que vale para esta requisição, e só para ela: hoje, a sessão de banco.

    É um objeto mutável, e não a sessão guardada direto no contextvar, porque
    o contexto só viaja de cima para baixo: o middleware não enxergaria um
    `.set()` feito na rota, mas enxerga a mudança de um atributo deste objeto.
    É assim que o `finally` do middleware consegue fechar a sessão que o
    controller criou.
    """

    def __init__(self) -> None:
        self.db_session: Optional[Session] = None

    def get_or_create_session(self) -> Session:
        if self.db_session is None:
            self.db_session = SessionLocal()

        return self.db_session


_context: ContextVar[Optional[Context]] = ContextVar("context", default=None)


def open_context() -> Context:
    """Prepara o contexto desta requisição. Chamada só pelo session_manager."""
    context = Context()
    _context.set(context)

    return context


def clear_context() -> None:
    """Tira o contexto de circulação no fim da requisição.

    Sem isto, fora de uma requisição o `get_context` devolveria o contexto
    anterior, com a sessão já fechada — e sessão fechada do SQLAlchemy reabre
    sozinha na próxima query, tomando uma conexão que ninguém fecharia.
    """
    _context.set(None)


def get_context() -> Context:
    """Devolve o contexto desta requisição. Quem chama é o BaseController."""
    context = _context.get()

    if context is None:
        raise Exception(
            "Nao existe contexto neste trabalho. "
            + "Quem prepara o contexto de cada requisicao e o middleware "
            + "src/middlewares/session_manager.py. Se voce chegou aqui, ele nao rodou."
        )

    return context
