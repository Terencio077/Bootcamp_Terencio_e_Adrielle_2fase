def only_digits(document_number: str) -> str:
    return "".join(character for character in document_number if character.isdigit())
