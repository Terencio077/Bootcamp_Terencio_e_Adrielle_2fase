def only_digits(document_number: str) -> str:
    """O documento só com os dígitos: "123.456.789-09" vira "12345678909".

    O contrato aceita CPF e CNPJ, com ou sem pontuação. Guardar só os
    dígitos é o que faz o histórico de uma pessoa ser um só, venha o
    documento escrito do jeito que vier.

    O motor não recusa um Pix por dígito verificador: quem recebe o Pix já
    passou pelo cadastro (onboarding fica fora do escopo do desafio), e
    devolver 422 aqui travaria um Pix por um problema que não é de fraude.
    """
    return "".join(character for character in document_number if character.isdigit())
