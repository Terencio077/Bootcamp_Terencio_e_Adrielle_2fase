from fastapi import Body, status
from fastapi.responses import JSONResponse

from controllers import PixTransactionController
from utils.schema_handler import SchemaHandler


class PixTransactionResource:
    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict = Body(...)) -> JSONResponse:
        analysis, created = PixTransactionController().create(payload)

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return JSONResponse(content=analysis, status_code=status_code)

    def on_get(self, pix_id: str) -> JSONResponse:
        analysis = PixTransactionController().get(pix_id)

        return JSONResponse(content=analysis, status_code=status.HTTP_200_OK)
