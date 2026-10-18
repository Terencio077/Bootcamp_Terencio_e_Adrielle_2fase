import functools
import json
import os

from jsonschema import RefResolver, ValidationError, validate

from constants import SCHEMA_PATH
from errors import InvalidSchema


class SchemaCache:
    """Guarda os schemas já lidos do disco, pra não reler a cada requisição.

    Um schema é um arquivo .json que não muda enquanto a API está no ar.
    Ler o disco a cada POST seria trabalho repetido — então a primeira
    requisição lê e guarda, e as próximas pegam daqui.

    O dicionário é de CLASSE, não de instância: existe um só, e ninguém
    precisa passar o cache adiante.
    """

    schemas = {}

    @staticmethod
    def get_schema(schema_file_name: str) -> dict:
        schema_path = os.path.join(SCHEMA_PATH, schema_file_name)

        if schema_path in SchemaCache.schemas:
            return SchemaCache.schemas[schema_path]

        if not os.path.isfile(schema_path):
            raise Exception(
                f"Nao encontrei o schema '{schema_file_name}' em {SCHEMA_PATH}. "
                + "Ou o arquivo nao existe, ou o nome escrito na rota esta diferente."
            )

        with open(schema_path, "r", encoding="utf-8") as arquivo:
            schema = json.loads(arquivo.read())

        SchemaCache.schemas[schema_path] = schema

        return schema


class SchemaHandler:
    """Confere o corpo da requisição contra um arquivo de schema.

    ────────────────────────────────────────────────────────────────
    POR QUE JSON SCHEMA, E NÃO O PYDANTIC
    ────────────────────────────────────────────────────────────────
    O FastAPI já sabe validar sozinho: bastava escrever uma classe que
    herda de BaseModel e pedi-la na assinatura da rota. Foi assim que
    este projeto começou, e funcionava.

    A troca não é técnica, é de vocabulário. Nos serviços da QI Tech o
    contrato de entrada é um arquivo .json escrito em JSON Schema — um
    padrão que existe fora do Python e que o time inteiro lê, inclusive
    quem integra com a API e nunca vai abrir este repositório. Um
    projeto de estudo que ensina o jeito do framework ensina uma coisa
    a mais pra desaprender depois.

    Repare no que se ganha de quebra: o contrato virou um arquivo que
    se lê sozinho. Quem vai integrar com esta API precisa saber o que
    mandar no corpo — e agora recebe o .json, sem precisar abrir o
    repositório nem saber Python.

    ────────────────────────────────────────────────────────────────
    O QUE ISSO CUSTA
    ────────────────────────────────────────────────────────────────
    O corpo chega como um dicionário cru, e não como um objeto com
    campos. Onde antes se escrevia `payload.hello`, agora se escreve
    `payload["hello"]` — e o editor não completa mais o nome do campo
    nem avisa se você digitar errado. O contrato saiu do código e foi
    morar num arquivo à parte: melhor pra quem integra, um pouco pior
    pra quem digita.
    """

    @staticmethod
    def validate(schema_file_name: str):

        def decorator_validate(func):
            @functools.wraps(func)
            def wrapper_validate(*args, **kwargs):
                if "payload" not in kwargs:
                    raise Exception(
                        f"A rota '{func.__name__}' foi decorada com o SchemaHandler, mas nao "
                        + "tem um parametro chamado 'payload'. E de la que sai o corpo a validar."
                    )

                schema = SchemaCache.get_schema(schema_file_name)
                resolver = RefResolver(f"file://{SCHEMA_PATH}/", None)

                try:
                    validate(kwargs["payload"], schema, resolver=resolver)
                except ValidationError as error:
                    raise InvalidSchema(describe_schema_error(error))

                return func(*args, **kwargs)

            return wrapper_validate

        return decorator_validate


def describe_schema_error(error: ValidationError) -> str:
    """Diz o que estava errado e ONDE, quando o campo é aninhado.

    O jsonschema já escreve uma boa mensagem ("'hello' is a required
    property"), mas ela não diz em que parte do JSON o problema está.
    Para um campo na raiz isso não faz falta; para um campo dentro de
    uma lista dentro de um objeto, faz toda.
    """
    location = []
    for part in error.absolute_path:
        location.append(str(part))

    if location:
        return f"{error.message} in {'.'.join(location)}"

    return error.message
