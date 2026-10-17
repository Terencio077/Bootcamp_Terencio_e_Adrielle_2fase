from errors.base_error import QIException


class PixTransactionNotFound(QIException):
    code = "QIT003004"

    def __init__(self, pix_id) -> None:
        title = "Pix transaction not found"
        http_status = 404
        description = f"There is no analysis for the Pix {pix_id}."
        translation = "Não existe análise gravada para este Pix."
        super().__init__(title, self.code, http_status, description, translation)


class PixIdConflict(QIException):
    code = "QIT003009"

    def __init__(self, pix_id) -> None:
        title = "Pix id reused with a different body"
        http_status = 409
        description = (
            f"The Pix {pix_id} was already analysed with different data. "
            + "An id identifies one Pix; the original analysis is kept."
        )
        translation = "Este id de Pix já foi analisado com outros dados. A análise original foi mantida."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidTransactionDate(QIException):
    code = "QIT003022"

    def __init__(self, value) -> None:
        title = "Invalid transaction date"
        http_status = 422
        description = f"The transaction_date {value} is not an ISO 8601 date with a timezone offset."
        translation = "A data da transação precisa estar no formato ISO 8601 com fuso horário."
        super().__init__(title, self.code, http_status, description, translation)
