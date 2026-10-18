import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "antifraud-service", "src"))

from rules import (  # noqa: E402
    APPROVED, DEFAULT_PARAMETERS, REJECTED, TWO_FACTOR_REQUIRED,
    DecisionEngine, DestinationHistory, History, PastPix, PixRequest,
)

NOW = datetime.fromisoformat("2026-10-15T14:00:00-03:00")
OLD = datetime.fromisoformat("2020-01-01T10:00:00-03:00")
PAYER = "12345678909"
COMPANY = "12345678000195"
SHORT = {APPROVED: "aprova", TWO_FACTOR_REQUIRED: "2fa", REJECTED: "recusa"}


def pix(amount, doc="98765432100", account=("60701190", "0001", "111"), opened=OLD, device="dev-a",
        channel="app", when=NOW, lat=None, lon=None):
    return PixRequest("calib", amount, when, PAYER, OLD, account, doc, opened, device, channel, "1.1.1.1", lat, lon)


def past(days_ago=0.0, minutes_ago=0.0, amount=10000, doc="98765432100", account=("60701190", "0001", "111"),
         device="dev-a", status=APPROVED, channel="app", lat=None, lon=None):
    when = NOW - timedelta(days=days_ago, minutes=minutes_ago)
    return PastPix(when, amount, status, device, channel, account, doc, lat, lon)


def hist(items, other_payers=0, rejected_payers=0):
    items = sorted(items, key=lambda p: p.transaction_date, reverse=True)
    return History(items, DestinationHistory(other_payers, rejected_payers))


def everyday(days=20, amount=8000):
    return [past(days_ago=d, amount=amount, doc="11111111111", account=("1", "1", "mkt")) for d in range(1, days + 1)]


SCENARIOS = [
    ("Pix pequeno do dia a dia", "legit", {"aprova"}, pix(5000, doc="11111111111", account=("1", "1", "mkt")), hist(everyday())),
    ("Aluguel de sempre (4º mês)", "legit", {"aprova"}, pix(150000), hist(everyday() + [past(days_ago=30 * m, amount=150000) for m in (1, 2, 3)])),
    ("Aluguel com reajuste de 10%", "legit", {"aprova"}, pix(165000), hist(everyday() + [past(days_ago=30 * m, amount=150000) for m in (1, 2, 3)])),
    ("Pix para conta própria em outro banco", "legit", {"aprova"}, pix(300000, doc=PAYER, account=("2", "2", "eu")), hist(everyday())),
    ("Troca de celular, Pix pequeno", "legit", {"aprova", "2fa"}, pix(5000, doc="11111111111", account=("1", "1", "mkt"), device="dev-novo"), hist(everyday())),
    ("Troca de celular, aluguel", "legit", {"2fa"}, pix(150000, device="dev-novo"), hist(everyday() + [past(days_ago=30 * m, amount=150000) for m in (1, 2, 3)])),
    ("Compra cara excepcional (R$ 4.000, loja antiga)", "legit", {"2fa"}, pix(400000, doc=COMPANY, account=("3", "3", "loja")), hist(everyday())),
    ("Prestador novo (conta de 20 dias), R$ 300", "legit", {"aprova", "2fa"}, pix(30000, doc="22222222222", account=("4", "4", "pr"), opened=NOW - timedelta(days=20)), hist(everyday())),
    ("Cliente da lanchonete (CNPJ com 12 pagadores/h)", "legit", {"aprova"}, pix(3500, doc=COMPANY, account=("5", "5", "lan")), hist(everyday(), other_payers=11)),
    ("Autônomo com CPF novo recebendo 4 clientes/h", "legit", {"aprova", "2fa"}, pix(8000, doc="33333333333", account=("6", "6", "aut"), opened=NOW - timedelta(days=10)), hist(everyday(), other_payers=3)),
    ("Churrasco: 6 amigos em 10 min", "legit", {"aprova", "2fa"}, pix(4000, doc="44444444444", account=("7", "7", "a")), hist(everyday() + [past(minutes_ago=i + 1, amount=4000, doc=f"5555555555{i}", account=("7", "7", f"x{i}")) for i in range(5)])),
    ("Empréstimo de R$ 2.000 ao amigo de sempre", "legit", {"2fa"}, pix(200000, doc="66666666666", account=("8", "8", "am")), hist(everyday() + [past(days_ago=d, amount=5000, doc="66666666666", account=("8", "8", "am")) for d in (3, 10, 17)])),
    ("Pix noturno de R$ 300", "legit", {"aprova"}, pix(30000, doc="11111111111", account=("1", "1", "mkt"), when=NOW.replace(hour=22)), hist(everyday())),
    ("Pix noturno de R$ 1.500 (aluguel atrasado)", "legit", {"2fa"}, pix(150000, when=NOW.replace(hour=22)), hist(everyday() + [past(days_ago=30 * m, amount=150000) for m in (1, 2, 3)])),
    ("Primeiro Pix de cliente novo, R$ 150", "legit", {"aprova", "2fa"}, pix(15000), hist([])),
    ("Viagem: SP pela manhã, Rio 6h depois", "legit", {"aprova"}, pix(5000, doc="11111111111", account=("1", "1", "mkt"), lat=-22.9, lon=-43.2), hist(everyday() + [past(minutes_ago=360, amount=5000, doc="11111111111", account=("1", "1", "mkt"), lat=-23.55, lon=-46.63)])),
    ("Falso parente: R$ 3.000 p/ conta de 2 dias", "fraude", {"recusa"}, pix(300000, doc="77777777777", account=("9", "9", "lar"), opened=NOW - timedelta(days=2)), hist(everyday())),
    ("Falso parente: R$ 1.500 p/ conta de 5 dias", "fraude", {"recusa", "2fa"}, pix(150000, doc="77777777777", account=("9", "9", "lar"), opened=NOW - timedelta(days=5)), hist(everyday())),
    ("Conta roubada: celular novo, R$ 5.000 p/ conta nova", "fraude", {"recusa"}, pix(500000, doc="77777777777", account=("9", "9", "lar"), opened=NOW - timedelta(days=3), device="dev-ladrao"), hist(everyday())),
    ("Conta roubada: celular novo, internet banking, R$ 2.000", "fraude", {"recusa", "2fa"}, pix(200000, doc="77777777777", account=("9", "9", "x"), device="dev-ladrao", channel="internet_banking"), hist(everyday())),
    ("Esvaziamento: 4º Pix de R$ 1.500 no dia p/ destinos novos", "fraude", {"recusa", "2fa"}, pix(150000, doc="88888888880", account=("9", "1", "a")), hist(everyday() + [past(minutes_ago=60 * i, amount=150000, doc=f"8888888888{i}", account=("9", "1", f"b{i}")) for i in (1, 2, 3)])),
    ("Conta laranja: 10º pagador/h, CPF de 3 dias", "fraude", {"recusa"}, pix(9000, doc="77777777777", account=("9", "9", "lar"), opened=NOW - timedelta(days=3)), hist(everyday(), other_payers=9)),
    ("Conta laranja: CPF antigo, 10 pagadores/h", "fraude", {"recusa", "2fa"}, pix(9000, doc="77777777777", account=("9", "9", "lar")), hist(everyday(), other_payers=9)),
    ("Destino já barrado para 3 vítimas", "fraude", {"recusa", "2fa"}, pix(50000, doc="77777777777", account=("9", "9", "lar"), opened=NOW - timedelta(days=10)), hist(everyday(), rejected_payers=3)),
    ("Fracionamento: 3º Pix de R$ 199 em 1h, celular novo", "fraude", {"recusa", "2fa"}, pix(19900, doc="77777777777", account=("9", "9", "f"), device="dev-ladrao"), hist(everyday() + [past(minutes_ago=15 * i, amount=19500, doc="77777777777", account=("9", "9", "f"), device="dev-ladrao", status=TWO_FACTOR_REQUIRED) for i in (1, 2)])),
    ("Sequestro relâmpago: R$ 4.000 às 23h, aparelho de sempre", "fraude", {"recusa", "2fa"}, pix(400000, doc="77777777777", account=("9", "9", "s"), when=NOW.replace(hour=23)), hist(everyday())),
    ("Robô: 12º Pix em 10 min, celular novo", "fraude", {"recusa"}, pix(5000, doc="77777777777", account=("9", "9", "r"), device="dev-bot"), hist(everyday() + [past(minutes_ago=i * 0.7, amount=5000, doc="77777777777", account=("9", "9", "r"), device="dev-bot", status=TWO_FACTOR_REQUIRED) for i in range(1, 12)])),
    ("Viagem impossível + celular novo, R$ 1.000", "fraude", {"recusa", "2fa"}, pix(100000, doc="77777777777", account=("9", "9", "v"), device="dev-ladrao", lat=-3.1, lon=-60.0), hist(everyday() + [past(minutes_ago=30, lat=-23.55, lon=-46.63, doc="11111111111", account=("1", "1", "mkt"))])),
    ("Aquecimento: 3× R$ 1 em dias diferentes, depois R$ 5.000", "fraude", {"recusa", "2fa"}, pix(500000, doc="77777777777", account=("9", "9", "q")), hist(everyday() + [past(days_ago=d, amount=100, doc="77777777777", account=("9", "9", "q")) for d in (1, 2, 3)])),
    ("Aquecimento: 3× R$ 600 em dias diferentes, depois R$ 2.500", "fraude", {"recusa", "2fa"}, pix(250000, doc="77777777777", account=("9", "9", "q"), opened=NOW - timedelta(days=25)), hist(everyday() + [past(days_ago=d, amount=60000, doc="77777777777", account=("9", "9", "q")) for d in (1, 2, 3)])),
]


def run(params):
    engine = DecisionEngine(parameters=params)
    rows = []
    for name, kind, ok, p, h in SCENARIOS:
        d = engine.evaluate(p, h)
        rows.append((name, kind, ok, SHORT[d.status], d.identity_score, d.transaction_score,
                     ", ".join(f"{x.code}{x.points:+d}" if x.points else x.code for x in d.hits)))
    return rows


def summary(rows):
    legit = [r for r in rows if r[1] == "legit"]
    fraud = [r for r in rows if r[1] == "fraude"]
    return {
        "legit_recusados": sum(r[3] == "recusa" for r in legit),
        "legit_2fa_desnecessario": sum(r[3] == "2fa" and "2fa" not in r[2] for r in legit),
        "fraude_aprovada": sum(r[3] == "aprova" for r in fraud),
        "fraude_so_2fa": sum(r[3] == "2fa" for r in fraud),
        "acertos": sum(r[3] in r[2] for r in rows),
        "total": len(rows),
    }


def main():
    out = ["# Bateria de calibração (simulação)", "",
           "Gerado por `python scripts/calibracao.py`. Cenários montados pelo time, com o resultado aceitável "
           "definido **antes** de rodar o motor. Não são dados reais: mostram o raciocínio, não provam os números.", ""]
    rows = run(DEFAULT_PARAMETERS)
    s = summary(rows)
    out += ["## Motor atual", "",
            f"- Acertos: **{s['acertos']}/{s['total']}**, conformidade com os cenários sintéticos que nós mesmos escrevemos. Não é taxa de acerto em dados reais.",
            f"- Legítimos recusados: **{s['legit_recusados']}** · legítimos com 2FA não previsto: **{s['legit_2fa_desnecessario']}**",
            f"- Fraudes aprovadas: **{s['fraude_aprovada']}** · fraudes que só pediram 2FA: **{s['fraude_so_2fa']}**", "",
            "| Cenário | Tipo | Aceitável | Motor | Ident. | Trans. | Regras | |", "|---|---|---|---|---|---|---|---|"]
    for name, kind, ok, got, i, t, rules in rows:
        out.append(f"| {name} | {kind} | {'/'.join(sorted(ok))} | **{got}** | {i} | {t} | {rules} | {'✅' if got in ok else '❌'} |")

    out += ["", "## Limiares alternativos", "",
            "Mesmos cenários, mudando só um limiar por vez.", "",
            "| Variação | Acertos | Legít. recusados | Legít. 2FA não previsto | Fraudes aprovadas | Fraudes só 2FA |",
            "|---|---|---|---|---|---|"]
    variants = [("Atual (2FA 30, recusa transação 60, identidade 80, ambos 40)", DEFAULT_PARAMETERS)]
    for v in (50, 70):
        variants.append((f"Recusa transação em {v}", replace(DEFAULT_PARAMETERS, transaction_reject_threshold=v)))
    for v in (70, 90):
        variants.append((f"Recusa identidade em {v}", replace(DEFAULT_PARAMETERS, identity_reject_threshold=v)))
    for v in (25, 35):
        variants.append((f"2FA a partir de {v}", replace(DEFAULT_PARAMETERS, two_factor_threshold=v)))
    variants.append(("Sem a regra 'ambos ≥ 40'", replace(DEFAULT_PARAMETERS, both_axes_reject_threshold=999)))
    for label, params in variants:
        s = summary(run(params))
        out.append(f"| {label} | {s['acertos']}/{s['total']} | {s['legit_recusados']} | {s['legit_2fa_desnecessario']} | "
                   f"{s['fraude_aprovada']} | {s['fraude_so_2fa']} |")
    text = "\n".join(out) + "\n"
    with open(os.path.join(ROOT, "CALIBRACAO.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
