"""Verificações de regressão do antifraude. Python 3.10+, sem pacotes extras.

Copie para a raiz do projeto e rode:
    python verificar_motor.py
    python verificar_motor.py --api

--api também cria cerca de 600 Pix fictícios na API local para conferir
o histórico real do banco. Não limpa dados existentes. Cada execução usa
documentos, contas e IDs próprios. O relatório TXT não inclui o token.
"""

import argparse
import hashlib
import importlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib import error, request

NOW = datetime.fromisoformat("2026-10-15T14:00:00-03:00")
OLD = datetime.fromisoformat("2020-01-01T10:00:00-03:00")
REPORT = {"verificador": "2026-10-17.1", "casos": [], "avisos": []}


class Failure(Exception):
    pass


def require(condition, message, observed=None):
    if not condition:
        raise Failure(message + (" | " + json.dumps(observed, ensure_ascii=False) if observed is not None else ""))


def number(length):
    return "8" + "".join(str(secrets.randbelow(10)) for _ in range(length - 1))


def token_from_environment(root):
    if os.environ.get("INTERNAL_TOKEN"):
        return os.environ["INTERNAL_TOKEN"]
    env = root / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            left, sep, right = line.strip().partition("=")
            if sep and left.strip() == "INTERNAL_TOKEN":
                value = right.strip()
                if value[:1] in ("'", '"') and value[-1:] == value[:1]:
                    value = value[1:-1]
                else:
                    value = value.split(" #", 1)[0].strip()
                return value
    return "default_token"


def short(result):
    meta = result.get("metadata", {})
    return {
        "status": result.get("status"), "scores": meta.get("scores", {}),
        "regras": [{"regra": h.get("rule"), "pontos": h.get("points"), "efeito": h.get("effect"),
                    "evidencia": h.get("evidence", {})}
                   for h in meta.get("rules_triggered", [])],
        "versao": meta.get("rules_version"),
    }


def validate(result):
    require(isinstance(result, dict) and result.get("status") in
            ("approved", "two_factor_required", "rejected"), "Resposta com status inválido")
    for hit in result.get("metadata", {}).get("rules_triggered", []):
        if str(hit.get("effect", "")).upper().startswith("FAILSAFE") or hit.get("evidence", {}).get("error"):
            raise Failure("Falha técnica de regra: este resultado não comprova a correção | "
                          + json.dumps(short(result), ensure_ascii=False))
    return result


class Client:
    def __init__(self, mode, modules, args, token, company=False):
        self.mode, self.modules, self.args, self.token = mode, modules, args, token
        self.payer = number(14 if company else 11)
        self.device = "test-" + uuid.uuid4().hex[:16]
        self.account = number(10)
        self.destinations = {}
        self.rows = []
        self.calls = 0

    def send(self, amount, when, payee=0, opened=OLD):
        if payee not in self.destinations:
            self.destinations[payee] = (number(11), number(10))
        doc, account = self.destinations[payee]
        payload = {
            "id": "verify-" + uuid.uuid4().hex,
            "amount": amount, "transaction_date": when.isoformat(),
            "source_account": {"branch": "0001", "account_number": self.account,
                               "opening_date": OLD.isoformat(), "owner": {"document_number": self.payer}},
            "destination_account": {"participant": "60701190", "branch": "0001", "account_number": account,
                                    "opening_date": opened.isoformat(), "owner": {"document_number": doc}},
            "source": {"device_id": self.device, "channel": "app", "ip": "198.51.100.23"},
        }
        self.calls += 1
        if self.mode == "API":
            req = request.Request(self.args.url.rstrip("/") + "/pix/transaction",
                                  data=json.dumps(payload).encode("utf-8"), method="POST",
                                  headers={"Content-Type": "application/json", "INTERNAL-TOKEN": self.token})
            try:
                with request.urlopen(req, timeout=self.args.timeout) as response:
                    body = json.load(response)
                    require(response.status == 201, "Esperava HTTP 201 para ID novo", {"http": response.status})
            except error.HTTPError as exc:
                # Não imprime headers, credenciais, corpo da requisição ou token.
                raise RuntimeError(f"API respondeu HTTP {exc.code}; confira serviço, schema e INTERNAL_TOKEN.") from None
            meta = body.get("metadata", {})
            version = meta.get("rules_version")
            if version:
                REPORT.setdefault("versoes_api", [])
                if version not in REPORT["versoes_api"]:
                    REPORT["versoes_api"].append(version)
            require(isinstance(body.get("key"), str) and bool(body["key"]), "Resposta da API sem key válida")
            return validate(body)

        m = self.modules
        current = m.PixRequest(
            pix_id=payload["id"], amount_cents=amount, transaction_date=when,
            source_document=self.payer, source_opening_date=OLD,
            destination_account=("60701190", "0001", account), destination_document=doc,
            destination_opening_date=opened, device_id=self.device, channel="app", ip="198.51.100.23",
        )
        visible = sorted((p for p in self.rows if when - timedelta(days=m.DEFAULT_PARAMETERS.history_days)
                          <= p.transaction_date <= when), key=lambda p: p.transaction_date, reverse=True)
        # Contexto completo: cobertura/limite do repository só são certificados pelo modo API.
        context = m.History(payer_pix=visible, destination=m.DestinationHistory())
        decision = m.DecisionEngine().evaluate(current, context)
        self.rows.append(m.PastPix(
            transaction_date=when, amount_cents=amount, status=decision.status,
            device_id=self.device, channel="app", destination_account=current.destination_account,
            destination_document=doc,
        ))
        return validate({"status": decision.status.lower(), "metadata": {
            "scores": {"identity": decision.identity_score, "transaction": decision.transaction_score},
            "rules_version": decision.rules_version,
            "rules_triggered": [{"rule": h.code, "points": h.points, "effect": h.effect,
                                 "evidence": h.evidence} for h in decision.hits],
        }})


def approved(result):
    require(result.get("status") == "approved", "Preparação mudou: Pix de controle não foi aprovado", short(result))


def profile(client):
    # Seed ainda visível ao formar o perfil, mas naturalmente fora da janela atual de 90 dias.
    approved(client.send(5000, NOW - timedelta(days=91)))
    for day in (6, 5, 4, 3, 2, 1):
        approved(client.send(100000, NOW - timedelta(days=day)))


def novelty_case(client, amount):
    profile(client)
    first = client.send(amount, NOW, payee=99, opened=NOW - timedelta(days=3))
    second = client.send(amount, NOW + timedelta(seconds=1), payee=99, opened=NOW - timedelta(days=3))
    rank = {"approved": 0, "two_factor_required": 1, "rejected": 2}
    observed = {"primeiro": short(first), "repeticao": short(second)}
    require(first.get("status") in ("two_factor_required", "rejected"),
            "A primeira tentativa já foi aprovada; conferir cenário/limiares", observed)
    require(second.get("status") in rank and rank[second["status"]] >= rank[first["status"]],
            "Restrição diminuiu após tentativa sem confirmação", observed)
    return observed


def daily_profile(client):
    approved(client.send(5000, NOW - timedelta(days=41)))
    approved(client.send(150000, NOW - timedelta(days=40)))
    for day in range(20, 0, -1):
        approved(client.send(8000, NOW - timedelta(days=day), payee=1))
    prior = []
    for index, hours in enumerate((3, 2, 1)):
        prior.append(client.send(150000, NOW - timedelta(hours=hours), payee=10 + index))
    return prior


def boundary_case(factory):
    observed = []
    for amount in (199999, 200000):
        client = factory()
        prior = daily_profile(client)
        exposure = sum(150000 for p in prior if p.get("status") in ("approved", "two_factor_required"))
        result = client.send(amount, NOW, payee=99)
        observed.append({"valor_centavos": amount, "exposicao_anterior_centavos": exposure,
                         "anteriores": [p.get("status") for p in prior], "resultado": short(result)})
    require(all(x["exposicao_anterior_centavos"] > 200000 for x in observed),
            "Preparação mudou: operações anteriores já foram barradas; conferir manualmente", observed)
    require(all(x["resultado"]["status"] != "approved" for x in observed),
            "Soma anterior já excedia o piso diário, mas um candidato foi aprovado", observed)
    return observed


def cutoff_case(client):
    approved(client.send(5000, NOW - timedelta(days=60)))
    for index, minutes in enumerate(reversed([1 + 18 * k for k in range(500)]), 1):
        approved(client.send(5000, NOW - timedelta(minutes=minutes)))
        if client.mode == "API" and index % 100 == 0:
            print(f"    Histórico: {index}/500", flush=True)
    result = client.send(5000, NOW, payee=99, opened=NOW - timedelta(days=20))
    observed = {"registros_historicos": 501, "resultado": short(result),
                "escopo": "repository/banco pela API" if client.mode == "API" else "histórico completo no motor"}
    require(result.get("status") != "approved",
            "R$ 50 para destino recente foi aprovado após preparar 501 registros", observed)
    return observed


def rent_case(client, night=False):
    approved(client.send(5000, NOW - timedelta(days=61)))
    for day in (60, 30, 1):
        approved(client.send(150000, NOW - timedelta(days=day)))
    result = client.send(150000, NOW.replace(hour=22) if night else NOW)
    require(result.get("status") == ("two_factor_required" if night else "approved"),
            "Controle legítimo mudou: aluguel diurno/noturno", short(result))
    return short(result)


def run_case(name, mode, function):
    started = time.perf_counter()
    row = {"nome": name, "modo": mode}
    try:
        row["observado"] = function()
        row["resultado"] = "PASSOU"
    except Failure as exc:
        row.update(resultado="FALHOU", detalhe=str(exc))
    except Exception as exc:
        row.update(resultado="ERRO", detalhe=f"{type(exc).__name__}: {str(exc)[:600]}")
    row["segundos"] = round(time.perf_counter() - started, 3)
    REPORT["casos"].append(row)
    print(f"[{row['resultado']}] {mode}: {name}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", action="store_true", help="Também testa a API e cria histórico fictício local")
    parser.add_argument("--url", default=os.environ.get("ANTIFRAUD_URL", "http://localhost:8005"))
    parser.add_argument("--projeto", type=Path, help="Raiz do projeto se o script estiver em outra pasta")
    parser.add_argument("--timeout", type=float, default=15, help="Timeout de cada chamada HTTP, em segundos")
    args = parser.parse_args()
    candidates = [args.projeto] if args.projeto else [Path.cwd(), Path(__file__).resolve().parent]
    root = next((p.resolve() for p in candidates if p and (p / "services/antifraud-service/src/rules").is_dir()), None)
    if root is None:
        parser.error("Execute na raiz do projeto (pasta que contém services/) ou use --projeto CAMINHO.")
    REPORT.update(data=datetime.now().isoformat(timespec="seconds"), projeto=root.name, python=sys.version.split()[0])
    try:
        REPORT["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                          capture_output=True, text=True, timeout=3, check=True).stdout.strip()
        REPORT["alteracoes_rastreadas"] = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                                              cwd=root, capture_output=True, text=True, timeout=3).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        REPORT["commit"] = "indisponivel"
    REPORT["sha256_fontes"] = {}
    for rel in ("rules/parameters.py", "rules/transaction_rules.py", "rules/trust_rules.py", "rules/context.py",
                "repositories/history_repository.py", "controllers/pix_transaction_controller.py"):
        p = root / "services/antifraud-service/src" / rel
        if p.is_file():
            REPORT["sha256_fontes"][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    sys.path.insert(0, str(root / "services/antifraud-service/src"))
    modules = None
    try:
        modules = importlib.import_module("rules")
        REPORT["versao_local"] = modules.RULES_VERSION
    except Exception as exc:
        REPORT["avisos"].append(f"Import do motor local falhou: {type(exc).__name__}: {str(exc)[:200]}")
    token = token_from_environment(root)
    modes = ["MOTOR"] if modules is not None else []
    if args.api:
        try:
            with request.urlopen(args.url.rstrip("/") + "/health_check", timeout=args.timeout) as response:
                require(response.status in (200, 204), "Health check inesperado")
            modes.append("API")
        except Exception as exc:
            REPORT["casos"].append({"nome": "Disponibilidade da API", "modo": "API", "resultado": "ERRO",
                                    "detalhe": f"{type(exc).__name__}: serviço inacessível; rode docker compose up -d --build --wait."})
    else:
        REPORT["avisos"].append("Corte de 500 no repository NÃO certificado: rode novamente com --api para testar o banco real.")
    for mode in modes:
        print(f"\nExecutando modo {mode}...", flush=True)
        factory = lambda company=False: Client(mode, modules, args, token, company=company)
        run_case("TX08: repetição após pendência", mode, lambda: novelty_case(factory(), 100000))
        run_case("TX08: repetição após recusa", mode, lambda: novelty_case(factory(), 300000))
        run_case("TX05: fronteira R$ 1.999,99 / R$ 2.000", mode, lambda: boundary_case(factory))
        run_case("Histórico 501: soma diária", mode, lambda: cutoff_case(factory(company=True)))
        run_case("Controle: aluguel diurno recorrente", mode, lambda: rent_case(factory()))
        run_case("Controle: piso noturno com recorrência", mode, lambda: rent_case(factory(), night=True))
    if REPORT.get("versoes_api") and REPORT.get("versao_local") not in REPORT["versoes_api"]:
        REPORT["avisos"].append("Versão informada pela API difere da local; reconstrua o serviço antes de comparar.")
    REPORT["resumo"] = {name: sum(c["resultado"] == name for c in REPORT["casos"])
                        for name in ("PASSOU", "FALHOU", "ERRO")}
    if not REPORT["casos"]:
        REPORT["avisos"].append("Nenhum caso executado: verifique imports e ambiente.")
    text = "VERIFICACAO DO MOTOR ANTIFRAUDE\n\n" + json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n"
    output = root / ("resultado_motor_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt")
    output.write_text(text, encoding="utf-8")
    print("\nResumo:", REPORT["resumo"])
    print("Relatório:", output.name)
    print("Envie somente esse TXT ao ChatGPT. Não contém o token.")
    if not args.api:
        print("Para conferir também o repository/banco: python verificar_motor.py --api")
    return 2 if REPORT["resumo"]["ERRO"] or not REPORT["casos"] else (1 if REPORT["resumo"]["FALHOU"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
