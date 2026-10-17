"""O que o motor enxerga: o Pix de agora e o passado dele.

Estas classes são a fronteira do motor. Do lado de fora, o repository
consulta o banco e monta um `History`; do lado de dentro, as regras só
leem. Nenhuma regra fala com o banco, com a rede ou com o relógio do
servidor — e é isso que as deixa:

• rápidas: o banco é consultado UMA vez por Pix, antes das regras, com
  duas consultas indexadas (o passado do pagador e o do destino);
• testáveis sem banco: um teste monta um `History` à mão e confere a
  regra em milissegundos (services/antifraud-service/tests/unit);
• determinísticas: o "agora" de toda regra é a `transaction_date` do Pix,
  não o relógio do servidor. O mesmo Pix com o mesmo passado dá sempre a
  mesma decisão.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

APPROVED = "APPROVED"
TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
REJECTED = "REJECTED"

# Referência para CONTAR DIAS (recorrência de recebedor e de aparelho):
# horário de Brasília, UTC-3 fixo (o Brasil não tem horário de verão desde
# 2019). Contar "dias diferentes" com o fuso que veio em cada Pix deixaria o
# mesmo instante, escrito com offsets diferentes, virar três dias. As regras
# de HORA DO DIA (noite, madrugada) continuam no relógio de quem paga — o
# fuso do próprio Pix —, porque a pergunta delas é outra.
BUSINESS_TIMEZONE = timezone(timedelta(hours=-3))


def business_date(moment: datetime) -> date:
    """O dia do calendário de Brasília em que o instante caiu."""
    return moment.astimezone(BUSINESS_TIMEZONE).date()


# Chave de uma conta em qualquer banco: ISPB + agência + conta.
AccountKey = Tuple[str, str, str]


@dataclass(frozen=True)
class PixRequest:
    """O Pix que está sendo analisado, já normalizado (documento só com dígitos)."""

    pix_id: str
    amount_cents: int
    transaction_date: datetime          # com fuso: é o relógio das regras
    source_document: str
    source_opening_date: datetime
    destination_account: AccountKey
    destination_document: str
    destination_opening_date: datetime
    device_id: str
    channel: str
    ip: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def local_hour(self) -> int:
        """A hora no relógio de quem pagou (o fuso que veio no Pix)."""
        return self.transaction_date.hour

    @property
    def payer_is_person(self) -> bool:
        return len(self.source_document) == 11


@dataclass(frozen=True)
class PastPix:
    """Um Pix anterior DESTE pagador, com a decisão que recebeu."""

    transaction_date: datetime
    amount_cents: int
    status: str
    device_id: str
    channel: str
    destination_account: AccountKey
    destination_document: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def local_hour(self) -> int:
        return self.transaction_date.hour

    @property
    def money_may_have_left(self) -> bool:
        """Aprovado, ou 2FA (cujo resultado o motor não fica sabendo).

        O desafio não tem retorno do 2FA. Na dúvida, um Pix que pediu 2FA
        conta como dinheiro que saiu: para soma do dia, limite noturno e
        limite de dispositivo, subestimar o que saiu é o erro perigoso.
        """
        return self.status in (APPROVED, TWO_FACTOR_REQUIRED)


@dataclass(frozen=True)
class DestinationHistory:
    """O passado da conta que vai RECEBER, olhando todos os pagadores."""

    distinct_other_payers_in_window: int = 0   # pagadores diferentes do atual, na janela de concentração
    rejected_payers_in_window: int = 0         # pagadores distintos recusados por risco da transação


@dataclass(frozen=True)
class History:
    payer_pix: List[PastPix] = field(default_factory=list)   # do mais novo para o mais velho
    destination: DestinationHistory = field(default_factory=DestinationHistory)

    def payer_since(self, moment: datetime) -> List[PastPix]:
        return [past for past in self.payer_pix if past.transaction_date >= moment]

    def payer_within(self, now: datetime, window: timedelta) -> List[PastPix]:
        return self.payer_since(now - window)
