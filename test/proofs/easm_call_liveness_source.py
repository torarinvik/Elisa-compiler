"""Inspect production and proof bodies for EASM call liveness."""


def compact(value: str) -> str:
    return " ".join(value.split())

def source_body(source: str, signature: str) -> str:
    if signature not in source:
        raise SystemExit(f"missing production function: {signature}")
    return source.split(signature, 1)[1].split("\n        def ", 1)[0]

def proof_body(source: str, name: str) -> str:
    signature = f"def {name}("
    if signature not in source:
        raise SystemExit(f"missing proof function: {name}")
    return source.split(signature, 1)[1].split("\ndef ", 1)[0].split(":\n", 1)[1]

def return_expression(source: str, name: str) -> str:
    body = proof_body(source, name)
    if "return " not in body:
        raise SystemExit(f"proof function has no return expression: {name}")
    return compact(body.split("return ", 1)[1])
