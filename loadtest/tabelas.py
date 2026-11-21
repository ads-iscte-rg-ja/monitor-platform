#!/usr/bin/env python3
"""Gera as tabelas LaTeX dos testes de carga a partir de docs/metrics/<iteração>/carga/*.json.

Uso:  loadtest/tabelas.py <iteração> [--antes <iteração>]

Escreve em docs/metrics/<iteração>/: carga-sc1.tex, carga-sc2.tex, carga-sc5.tex,
carga-sensibilidade.tex, carga-sc3.tex e carga-sc4.tex (o relatório inclui-as com \\gerado, depois de "make dados ITER=...").
Com --antes, cada tabela acrescenta a coluna da iteração anterior (antes/depois).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICAS = Path(__file__).resolve().parent.parent / "docs" / "metrics"


def carregar(iteracao: str, medicao: str) -> dict | None:
    caminho = METRICAS / iteracao / "carga" / f"{medicao}.json"
    return json.loads(caminho.read_text()) if caminho.exists() else None


def valor(m: dict | None, *chaves):
    for chave in chaves:
        if m is None:
            return None
        m = m.get(chave) if isinstance(m, dict) else None
    return m


def num(x, casas: int = 0, unidade: str = "") -> str:
    if x is None:
        return "---"
    texto = f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", "\\,")
    return f"{texto}{unidade}"


def p95_servidor(m: dict | None) -> str:
    v = valor(m, "servidor", "ingestao_p95_ms")
    # 10 s é o último limite do histograma (ADR-0004): acima disso só se sabe que é "pelo menos".
    return "$\\ge$ 10 s" if v is not None and v >= 10000 else num(v, 0, " ms")


def duracao(ms_valor) -> str:
    """Em milissegundos abaixo de 1 s, em segundos acima: 6 ms em vez de "0,01 s"."""
    if ms_valor is None:
        return "---"
    return num(ms_valor, 0, " ms") if ms_valor < 1000 else num(ms_valor / 1000, 2, " s")


def cumpre(ok) -> str:
    return "---" if ok is None else ("\\Sim" if ok else "\\Nao")


def nao_ok_pct(m: dict | None) -> float | None:
    codigos = valor(m, "servidor", "pedidos_por_codigo")
    if not codigos:
        return None
    total = sum(codigos.values())
    return 100 * sum(v for c, v in codigos.items() if c != "OK") / total if total else None


def pct_codigo(m: dict | None, codigo: int) -> float | None:
    """Percentagem de tentativas de envio que receberam o código gRPC indicado (contagem do k6)."""
    total = valor(m, "agente", "grpc_req_duration{ingestao:sim}", "count")
    if not total:
        return None
    return 100 * (valor(m, "agente", f"respostas_nao_ok{{codigo:{codigo}}}", "count") or 0) / total


def pct_outros(m: dict | None) -> float | None:
    """Percentagem de tentativas com erro que não seja rejeição por sobrecarga (código 8)."""
    total = valor(m, "agente", "grpc_req_duration{ingestao:sim}", "count")
    if not total:
        return None
    nao_ok = valor(m, "agente", "respostas_nao_ok", "count") or 0
    rejeicoes = valor(m, "agente", "respostas_nao_ok{codigo:8}", "count") or 0
    return 100 * (nao_ok - rejeicoes) / total


def integridade(m: dict | None) -> tuple[float | None, float | None, float | None]:
    confirmados = valor(m, "agente", "registos_confirmados", "count")
    bd = valor(m, "base_de_dados")
    gravados = None if bd is None else bd["stats"] + bd["erros"]
    return confirmados, gravados, None if bd is None else bd["duplicados"]


def linhas_sc1(m: dict | None) -> list[tuple[str, str, str, str]]:
    p95 = valor(m, "agente", "grpc_req_duration{ingestao:sim}", "p(95)")
    atraso = valor(m, "agente", "atraso_central{vizinho:sim}", "p(95)")
    perdidos = valor(m, "agente", "lotes_perdidos", "rate")
    cpu_med, cpu_max = valor(m, "servidor", "cpu_media_pct"), valor(m, "servidor", "cpu_max_pct")
    falhas = nao_ok_pct(m)
    confirmados, gravados, duplicados = integridade(m)
    segundos = valor(m, "agente", "duracao_s")
    return [
        ("p95 da ingestão (agente)", "$<$ 300 ms", num(p95, 0, " ms"), cumpre(None if p95 is None else p95 < 300)),
        ("p95 da ingestão (servidor)", "---", p95_servidor(m), "---"),
        ("Pedidos não OK", "0\\,\\%", num(falhas, 2, "\\,\\%"), cumpre(None if falhas is None else falhas == 0)),
        ("Lotes não entregues", "0", num(None if perdidos is None else perdidos * 100, 2, "\\,\\%"),
         cumpre(None if perdidos is None else perdidos == 0)),
        ("CPU do central, média / máx.", "$<$ 70\\,\\%", f"{num(cpu_med, 0)} / {num(cpu_max, 0, '\\,\\%')}",
         cumpre(None if cpu_max is None else cpu_max < 70)),
        ("Atraso p95 (exceto rajada)", "$<$ 5 s", duracao(atraso),
         cumpre(None if atraso is None else atraso < 5000)),
        ("Registos confirmados / s", "---", num(None if not confirmados or not segundos else confirmados / segundos, 0), "---"),
        ("Confirmados ao agente / gravados", "iguais",
         "---" if gravados is None else f"{num(confirmados)} / {num(gravados)}",
         cumpre(None if gravados is None else confirmados == gravados)),
        ("Duplicados na base de dados", "0", num(duplicados), cumpre(None if duplicados is None else duplicados == 0)),
    ]


def tabela(rotulo: str, legenda: str, cabecalho: list[str], linhas: list[list[str]], formato: str, nota: str = "") -> str:
    corpo = "\n".join("    " + " & ".join(l) + " \\\\" for l in linhas)
    nota_tex = f"\n  \\par\\smallskip\\footnotesize {nota}" if nota else ""
    return f"""\\begin{{table}}[htbp]
  \\centering\\small
  \\caption{{{legenda}}}
  \\label{{{rotulo}}}
  \\begin{{tabularx}}{{\\linewidth}}{{>{{\\raggedright\\arraybackslash}}X{formato[1:]}}}
    \\toprule
    {" & ".join(cabecalho)} \\\\
    \\midrule
{corpo}
    \\bottomrule
  \\end{{tabularx}}{nota_tex}
\\end{{table}}
"""


def com_antes(linhas_depois, linhas_antes):
    if linhas_antes is None:
        return [[d[0], d[1], d[2], d[3]] for d in linhas_depois]
    return [[d[0], d[1], a[2], d[2], d[3]] for d, a in zip(linhas_depois, linhas_antes)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("iteracao")
    ap.add_argument("--antes")
    a = ap.parse_args()
    destino = METRICAS / a.iteracao
    ambiente = "Ambiente: " + (destino / "carga" / "ambiente.txt").read_text().splitlines()[-1] if (destino / "carga" / "ambiente.txt").exists() else ""
    cab = ["Medida", "Alvo", "Medido", "Cumpre"] if not a.antes else ["Medida", "Alvo", a.antes, a.iteracao, "Cumpre"]
    fmt = "llrc" if not a.antes else "llrrc"

    def gerar(medicao: str, linhas_fn, rotulo: str, legenda: str, nota: str = "") -> None:
        depois = carregar(a.iteracao, medicao)
        if depois is None:
            return
        antes = linhas_fn(carregar(a.antes, medicao)) if a.antes else None
        (destino / f"{rotulo}.tex").write_text(
            tabela(f"tab:{rotulo}", f"{legenda} ({a.iteracao})", cab, com_antes(linhas_fn(depois), antes), fmt, nota))

    gerar("nominal", linhas_sc1, "carga-sc1", "Cenário SC1: 1\\,000 \\emph{hosts} em regime normal",
          "Atraso: do primeiro envio de um lote à confirmação, com as novas tentativas. " + ambiente)

    def linhas_sc5(m):
        vizinhos = valor(m, "agente", "atraso_central{fase:rajada,vizinho:sim}", "p(95)")
        rajada = valor(m, "agente", "atraso_central{perfil:rajada}", "p(95)")
        p95 = valor(m, "agente", "grpc_req_duration{ingestao:sim}", "p(95)")
        falhas = nao_ok_pct(m)
        return [
            ("Atraso p95 dos outros \\emph{hosts}, durante a rajada", "$<$ 5 s",
             duracao(vizinhos), cumpre(None if vizinhos is None else vizinhos < 5000)),
            ("Atraso p95 dos \\emph{hosts} em rajada", "---", duracao(rajada), "---"),
            ("p95 da ingestão (agente)", "---", num(p95, 0, " ms"), "---"),
            ("Pedidos não OK", "---", num(falhas, 2, "\\,\\%"), "---"),
        ]
    gerar("noisy-neighbour", linhas_sc5, "carga-sc5", "Cenário SC5: 1\\,\\% dos \\emph{hosts} em rajada de 200 logs/s")

    def linhas_sc2(m):
        hosts = valor(m, "hosts")
        concluidos = valor(m, "agente", "tempo_recuperacao", "count")
        todos = hosts is not None and concluidos == hosts
        # Só há tempo de absorção se todos os hosts entregaram o backlog dentro do tempo máximo.
        tempo = valor(m, "agente", "tempo_recuperacao", "max") if todos else None
        esperado = valor(m, "agente", "backlog_total", "count")
        # p95 do dashboard só na janela da recuperação (Prometheus); a média da medição inteira
        # diluía o impacto com os minutos de calma depois de o backlog acabar.
        dash = valor(m, "dashboard_p95_ms_durante_recuperacao")
        perdidos = valor(m, "agente", "lotes_perdidos", "rate")
        confirmados, gravados, duplicados = integridade(m)
        return [
            ("\\emph{Hosts} que entregaram todo o \\emph{backlog}", "todos",
             "---" if hosts is None else f"{num(concluidos or 0)} de {num(hosts)}", cumpre(None if hosts is None else todos)),
            ("Registos do \\emph{backlog} entregues", "todos",
             "---" if esperado is None else f"{num(confirmados)} de {num(esperado)}",
             cumpre(None if esperado is None else confirmados == esperado)),
            ("\\emph{Backlog} absorvido", "$\\le$ 15 min",
             num(None if tempo is None else tempo / 60000, 1, " min") if todos else "não absorvido",
             cumpre(False if not todos else tempo <= 900000)),
            ("p95 do \\emph{dashboard} durante a recuperação", "$<$ 1 s",
             "$\\ge$ 10 s" if dash is not None and dash >= 10000 else duracao(dash),
             cumpre(None if dash is None else dash < 1000)),
            ("Lotes não entregues", "0", num(None if perdidos is None else perdidos * 100, 2, "\\,\\%"),
             cumpre(None if perdidos is None else perdidos == 0)),
            ("Rejeições por sobrecarga (repetidas pelo agente)", "---", num(pct_codigo(m, 8), 1, "\\,\\%"), "---"),
            ("Erros (\\emph{timeouts} e outros)", "---", num(pct_outros(m), 1, "\\,\\%"), "---"),
            ("Esperas por ligação à BD", "---", num(valor(m, "servidor", "esperas_por_ligacao")), "---"),
            ("Confirmados ao agente / gravados", "iguais",
             "---" if gravados is None else f"{num(confirmados)} / {num(gravados)}",
             cumpre(None if gravados is None else confirmados == gravados)),
            ("Duplicados na base de dados", "0", num(duplicados), cumpre(None if duplicados is None else duplicados == 0)),
        ]
    gerar("recovery-storm", linhas_sc2, "carga-sc2", "Cenário SC2: recuperação após 1 h com o central em baixo")

    # Sensibilidade à hipótese do perfil de logs (relatório, secção 4.3), com --antes lado a lado.
    iteracoes = ([a.antes] if a.antes else []) + [a.iteracao]
    colunas = [(it, m, carregar(it, m)) for it in iteracoes for m in ("nominal", "nominal-x2", "nominal-x5")]
    colunas = [(it, m, d) for it, m, d in colunas if d is not None]
    if len(colunas) > 1:
        def col(f):
            return [f(d) for _, _, d in colunas]
        linhas = [
            ["p95 da ingestão (agente)"] + col(lambda d: num(valor(d, "agente", "grpc_req_duration{ingestao:sim}", "p(95)"), 0, " ms")),
            ["CPU média do central"] + col(lambda d: num(valor(d, "servidor", "cpu_media_pct"), 0, "\\,\\%")),
            ["Atraso p95 (exceto rajada)"] + col(lambda d: duracao(valor(d, "agente", "atraso_central{vizinho:sim}", "p(95)"))),
            ["Pedidos não OK"] + col(lambda d: num(nao_ok_pct(d), 2, "\\,\\%")),
            ["Cumpre SC1"] + col(lambda d: cumpre(all(l[3] != "\\Nao" for l in linhas_sc1(d)))),
        ]
        nomes = {"nominal": "×1", "nominal-x2": "×2", "nominal-x5": "×5"}
        cabecalho = ["Logs"] + [nomes[m] for _, m, _ in colunas]
        grupos = ""
        if len(iteracoes) > 1:
            por_it = [sum(1 for it, _, _ in colunas if it == x) for x in iteracoes]
            grupos = " & " + " & ".join(f"\\multicolumn{{{n}}}{{c}}{{{x}}}" for n, x in zip(por_it, iteracoes)) + " \\\\\n    "
        corpo = "\n".join("    " + " & ".join(l) + " \\\\" for l in linhas)
        (destino / "carga-sensibilidade.tex").write_text(f"""\\begin{{table}}[htbp]
  \\centering\\small
  \\caption{{Sensibilidade ao perfil de logs}}
  \\label{{tab:carga-sensibilidade}}
  \\begin{{tabular}}{{l{"r" * len(colunas)}}}
    \\toprule
    {grupos}{" & ".join(cabecalho)} \\\\
    \\midrule
{corpo}
    \\bottomrule
  \\end{{tabular}}
\\end{{table}}
""")
    escala = [(n, carregar(a.iteracao, f"capacidade-{n}")) for n in (1, 2, 3)]
    escala = [(n, m) for n, m in escala if m is not None]
    if escala:
        (destino / "carga-sc3.tex").write_text(tabela_sc3(escala, ambiente))
    # Com --antes, as colunas dizem "antes"/"depois"; as iterações vão na legenda.
    rotulo_it = {a.antes: "antes, ", a.iteracao: "depois, "} if a.antes else {a.iteracao: ""}
    fases = [(f"{rotulo_it[it]}{fase}", carregar(it, medicao)) for it in ([a.antes] if a.antes else []) + [a.iteracao]
             for fase, medicao in (("sem ret.", "dashboard-30d"), ("com ret.", "dashboard-30d-retencao"))]
    fases = [(nome, m) for nome, m in fases if m is not None]
    if fases:
        iteracoes = f"{a.antes} $\\rightarrow$ {a.iteracao}" if a.antes else a.iteracao
        (destino / "carga-sc4.tex").write_text(tabela_sc4(fases, ambiente, iteracoes))
    print(f"tabelas de carga escritas em {destino}")


# SC4: as consultas do dashboard do cenário dashboard-30d (k6/ingestao.js, CONSULTAS_30D).
CONSULTAS_SC4 = [("summary", "Resumo (\\texttt{/summary})"), ("pagina_dashboard", "Página do \\emph{dashboard}"),
                 ("metricas_24h", "Métricas de 24 h"), ("metricas_1m", "Métricas de 1 mês"),
                 ("erros", "Erros (\\texttt{/errors})"), ("erros_host", "Erros de um \\emph{host}"),
                 ("hosts", "\\emph{Hosts} (\\texttt{/hosts})")]


def tabela_sc4(fases: list[tuple[str, dict]], ambiente: str, iteracoes: str) -> str:
    """SC4: 31 dias de histórico, sem e com a retenção, antes e depois (ADR-0017)."""
    def col(f):
        return [f(m) for _, m in fases]

    def p95_consulta(m, nome):
        return duracao(valor(m, "agente", f"http_req_duration{{consulta:{nome}}}", "p(95)"))

    def rejeicoes(m):
        return num(pct_codigo(m, 8), 0, "\\,\\%")

    def retencao(m):
        r = valor(m, "servidor", "retencao") or {}
        if not r.get("execucoes"):
            return "---"
        return f"{num(r['duracao_media_s'], 1, ' s')} / {num(r.get('duracao_p95_s'), 1, ' s')}"

    linhas = [[f"p95: {rotulo}", "$<$ 1 s"] + col(lambda m, n=nome: p95_consulta(m, n)) for nome, rotulo in CONSULTAS_SC4]
    linhas += [
        ["p95 da ingestão (agente)", "$<$ 300 ms"] + col(lambda m: duracao(valor(m, "agente", "grpc_req_duration{ingestao:sim}", "p(95)"))),
        ["Rejeições por sobrecarga", "---"] + col(rejeicoes),
        ["Registos confirmados em 10 min", "---"] + col(lambda m: num(valor(m, "agente", "registos_confirmados", "count"))),
        ["Retenção: duração média / p95", "---"] + col(retencao),
        ["Expirados: variação por hora", "$\\le$ 0"] + col(lambda m: num(-(valor(m, "estado_bd", "removidos_por_hora") or 0)).replace("-", "$-$")),
        ["Lotes perdidos / duplicados", "0 / 0"] + col(lambda m: f"{num(valor(m, 'agente', 'lotes_perdidos', 'passes'))} / {num(valor(m, 'base_de_dados', 'duplicados'))}"),
    ]
    cab = ["Medida", "Alvo"] + [nome for nome, _ in fases]
    nota = ("31 dias de histórico de 1\\,000 \\emph{hosts} (89 M estatísticas, 239 M erros) e a carga nominal durante 10 min, "
            "com uma consulta do \\emph{dashboard} por segundo, à vez pelas sete. Com retenção: 30 dias, a cada minuto, lotes de 10\\,000. "
            + ambiente)
    return tabela("tab:carga-sc4", f"Cenário SC4: \\emph{{dashboard}} e retenção com 30 dias de dados ({iteracoes})", cab, linhas,
                  "ll" + "r" * len(fases), nota)


def tabela_sc3(escala: list[tuple[int, dict]], ambiente: str) -> str:
    """SC3: a mesma carga de capacidade com 1, 2 e 3 instâncias atrás do nginx."""
    base = valor(escala[0][1], "agente", "registos_confirmados", "count") if escala[0][0] == 1 else None
    alvo = {1: "---", 2: "$\\ge$ 1,8×", 3: "$\\ge$ 2,5×"}

    def col(f):
        return [f(n, m) for n, m in escala]

    def fator(n, m):
        c = valor(m, "agente", "registos_confirmados", "count")
        return "---" if not base or c is None else num(c / base, 2, "×")

    def jobs_ok(m):
        j = valor(m, "servidor", "jobs") or {}
        lideres, executores = j.get("lideres_max", {}), j.get("instancias_que_executaram", {})
        return bool(lideres) and all(v == 1 for v in list(lideres.values()) + list(executores.values()))

    def rejeicoes(m):
        return pct_codigo(m, 8)

    linhas = [
        ["Registos confirmados no teste"] + col(lambda n, m: num(valor(m, "agente", "registos_confirmados", "count"))),
        ["Débito face a 1 instância (alvo)"] + col(lambda n, m: f"{fator(n, m)} ({alvo[n]})" if n > 1 else "1×"),
        ["Débito no minuto de pico (registos/s)"] + col(lambda n, m: num(valor(m, "servidor", "registos_por_s_max_1m"))),
        ["p95 da ingestão (servidor)"] + col(lambda n, m: p95_servidor(m)),
        ["Rejeições por sobrecarga"] + col(lambda n, m: num(rejeicoes(m), 1, "\\,\\%")),
        ["Ligações à BD em uso, máx. (soma)"] + col(lambda n, m: f"{num(valor(m, 'servidor', 'ligacoes_bd_max'))} de {num(valor(m, 'servidor', 'ligacoes_bd_limite'))}"),
        ["CPU de cada instância, média"] + col(lambda n, m: num((valor(m, "cpu_contentores", "central", "media_pct") or 0) / n, 0, "\\,\\%")),
        ["CPU do PostgreSQL, média / máx."] + col(lambda n, m: f"{num(valor(m, 'cpu_contentores', 'postgres', 'media_pct'))} / {num(valor(m, 'cpu_contentores', 'postgres', 'max_pct'), 0, chr(92) + ',' + chr(92) + '%')}"),
        ["p95 do \\emph{dashboard}"] + col(lambda n, m: duracao(valor(m, "servidor", "dashboard_p95_ms"))),
        ["Cada \\emph{job} numa só instância"] + col(lambda n, m: cumpre(jobs_ok(m))),
        ["Duplicados na base de dados"] + col(lambda n, m: num(valor(m, "base_de_dados", "duplicados"))),
    ]
    cab = ["Medida"] + [f"{n} inst." for n, _ in escala]
    nota = ("Carga: 1\\,000 \\emph{hosts} a enviar lotes de 100 erros sem pausa, através do nginx, durante 5 min. "
            "CPU em \\% do limite de 2 vCPU de cada contentor. " + ambiente)
    return tabela("tab:carga-sc3", "Cenário SC3: a mesma carga com 1, 2 e 3 instâncias do central", cab, linhas,
                  "l" + "r" * len(escala), nota)


if __name__ == "__main__":
    main()
