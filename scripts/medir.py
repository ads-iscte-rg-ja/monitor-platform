#!/usr/bin/env python3
"""Mede os repositórios Go do Monitor e gera as tabelas do relatório.

Uso (a partir de qualquer pasta, com os repositórios lado a lado como em monitor-ws/):

    scripts/medir.py baseline            # iteração 0
    scripts/medir.py iter-1              # depois da iteração 1 (compara com a baseline)
    scripts/medir.py iter-1 --sem-integracao

Escreve em docs/metrics/<iteração>/:
    resumo.csv                 uma linha por (repositório, métrica): fonte do "antes/depois"
    ambiente.txt               commits medidos e versões das ferramentas (reprodutibilidade)
    dados/<repo>-*.csv         dados brutos: issues do lint, funções, acoplamento, cobertura
    <iteração>-*.tex           tabelas LaTeX (report/: make dados ITER=<iteração>)
    metricas-codigo-antes-depois.tex

Métricas e porquê: docs/PLANO_MELHORIAS.md §4 (GQM). Ferramentas, com as versões do CI:
golangci-lint (configuração partilhada lint/.golangci.yml), govulncheck, go test -cover,
tools/codemetrics (acoplamento de Martin e complexidade ciclomática por função).

Os testes de integração do central usam um PostgreSQL 16 temporário em Docker.
O govulncheck corre com a versão de Go declarada no go.mod, a mesma que o CI instala.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent
WS = PLATFORM.parent
LINT_CONFIG = PLATFORM / "lint" / ".golangci.yml"
CODEMETRICS = PLATFORM / "tools" / "codemetrics"

REPOS = ["monitor-central", "monitor-remote", "monitor-go-sdk", "monitor-hello-world"]
CURTO = {"monitor-central": "central", "monitor-remote": "remote",
         "monitor-go-sdk": "SDK", "monitor-hello-world": "hello-world"}
INTEGRACAO = {"monitor-central": "./internal/integration"}

LINTERS = ["depguard", "gocognit", "gocyclo", "dupl", "errcheck", "gosec",
           "govet", "staticcheck", "ineffassign", "unused", "revive"]
LIMITE = 15  # gocyclo e gocognit (lint/.golangci.yml)

ENV = {**os.environ, "GOWORK": "off", "CGO_ENABLED": "1"}


# --------------------------------------------------------------------------- utilitários

def sh(cmd: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=cwd, env=env or ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"falhou ({r.returncode}): {' '.join(cmd)} em {cwd}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def passo(msg: str) -> None:
    print(f"\033[1m== {msg}\033[0m", file=sys.stderr, flush=True)


def escrever_csv(path: Path, cabecalho: list[str], linhas: list[list]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cabecalho)
        w.writerows(linhas)


def tex(s: object) -> str:
    s = str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"), ("&", r"\&"),
                 ("#", r"\#"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}")]:
        s = s.replace(a, b)
    return s


def go_version(repo: Path) -> str:
    m = re.search(r"^go (\S+)", (repo / "go.mod").read_text(), re.M)
    return m.group(1)


# --------------------------------------------------------------------------- medições

def linhas_de_codigo(repo: Path) -> dict:
    prod = teste = ficheiros = 0
    for p in repo.rglob("*.go"):
        if any(part in {"vendor", ".git", "testdata"} for part in p.parts):
            continue
        n = sum(1 for linha in p.read_text(errors="ignore").splitlines() if linha.strip())
        ficheiros += 1
        if p.name.endswith("_test.go"):
            teste += n
        else:
            prod += n
    return {"loc_producao": prod, "loc_testes": teste, "ficheiros_go": ficheiros}


def golangci(repo: Path, config: Path, extra: list[str] | None = None) -> list[dict]:
    out = sh(["golangci-lint", "run", f"--config={config}", "--path-mode=abs",
              "--output.json.path=stdout", "--output.text.path=/dev/null",
              "--issues-exit-code=0", *(extra or []), "./..."], repo)
    dados, _ = json.JSONDecoder().raw_decode(out)
    return dados.get("Issues") or []


def lint(repo: Path, dados: Path) -> dict:
    issues = golangci(repo, LINT_CONFIG)
    escrever_csv(dados / f"{repo.name}-lint.csv", ["linter", "ficheiro", "linha", "mensagem"],
                 [[i["FromLinter"], os.path.relpath(i["Pos"]["Filename"], repo),
                   i["Pos"]["Line"], i["Text"]] for i in issues])
    c = Counter(i["FromLinter"] for i in issues)
    return {"lint_total": len(issues), **{f"lint_{k}": c.get(k, 0) for k in LINTERS}}


def funcoes(repo: Path, dados: Path, tmp: Path) -> dict:
    out = sh(["go", "run", ".", "-mode", "functions", "-dir", str(repo)], CODEMETRICS)
    rows = list(csv.DictReader(out.splitlines()))

    # Complexidade cognitiva de todas as funções: gocognit com limite 0.
    cfg = tmp / "cognitiva.yml"
    cfg.write_text('version: "2"\nrun: {tests: false}\nlinters:\n  default: none\n'
                   "  enable: [gocognit]\n  settings: {gocognit: {min-complexity: 0}}\n"
                   "issues: {max-issues-per-linter: 0, max-same-issues: 0, uniq-by-line: false}\n")
    cog = {}
    for i in golangci(repo, cfg):
        m = re.match(r"cognitive complexity (\d+)", i["Text"])
        cog[(os.path.relpath(i["Pos"]["Filename"], repo), i["Pos"]["Line"])] = int(m.group(1))
    for r in rows:
        r["cognitive"] = cog.get((r["file"], int(r["line"])), 0)

    escrever_csv(dados / f"{repo.name}-funcoes.csv",
                 ["pacote", "ficheiro", "linha", "funcao", "linhas", "ciclomatica", "cognitiva"],
                 [[r["package"], r["file"], r["line"], r["function"], r["lines"],
                   r["cyclomatic"], r["cognitive"]] for r in rows])

    ciclo = [int(r["cyclomatic"]) for r in rows] or [0]
    cogn = [int(r["cognitive"]) for r in rows] or [0]
    tam = [int(r["lines"]) for r in rows] or [0]
    return {
        "funcoes": len(rows),
        "ciclomatica_media": round(statistics.mean(ciclo), 2),
        "ciclomatica_max": max(ciclo),
        "ciclomatica_acima_limite": sum(c > LIMITE for c in ciclo),
        "cognitiva_media": round(statistics.mean(cogn), 2),
        "cognitiva_max": max(cogn),
        "cognitiva_acima_limite": sum(c > LIMITE for c in cogn),
        "linhas_por_funcao_media": round(statistics.mean(tam), 1),
        "linhas_por_funcao_max": max(tam),
    }


def acoplamento(repo: Path, dados: Path) -> tuple[dict, list[dict]]:
    out = sh(["go", "run", ".", "-mode", "coupling", "-dir", str(repo)], CODEMETRICS)
    (dados / f"{repo.name}-acoplamento.csv").write_text(out)
    rows = list(csv.DictReader(out.splitlines()))
    internos = [r for r in rows if not r["package"].startswith("cmd")]
    definidos = [float(r["distance"]) for r in internos if r["distance"]]
    return {
        "pacotes": len(rows),
        "ce_max": max((int(r["ce"]) for r in internos), default=0),
        "distancia_media": round(statistics.mean(definidos), 2) if definidos else "",
    }, internos


def perfil_cobertura(path: Path) -> dict[str, list[int]]:
    """Statements e statements cobertos por pacote. Junta blocos repetidos
    (com -coverpkg cada binário de teste escreve todos os blocos)."""
    blocos: dict[str, tuple[str, int, int]] = {}
    for linha in path.read_text().splitlines()[1:]:
        bloco, n, count = linha.rsplit(" ", 2)
        anterior = blocos.get(bloco)
        cnt = int(count) if anterior is None else max(anterior[2], int(count))
        blocos[bloco] = (bloco.split(":")[0].rsplit("/", 1)[0], int(n), cnt)
    por_pacote: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for pacote, n, cnt in blocos.values():
        por_pacote[pacote][0] += n
        por_pacote[pacote][1] += n if cnt > 0 else 0
    return dict(por_pacote)


def pct(cobertos: int, total: int) -> float:
    return round(100 * cobertos / total, 1) if total else 0.0


def postgres_temporario() -> tuple[str, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    nome = f"monitor-medir-{os.getpid()}"
    sh(["docker", "run", "-d", "--rm", "--name", nome, "-e", "POSTGRES_PASSWORD=test",
        "-e", "POSTGRES_DB=monitor_test", "-p", f"127.0.0.1:{porta}:5432", "postgres:16"], WS)
    for _ in range(60):
        r = subprocess.run(["docker", "exec", nome, "pg_isready", "-U", "postgres", "-d", "monitor_test",
                            "-h", "127.0.0.1"], capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(1)
    else:
        sys.exit("o PostgreSQL temporário não arrancou")
    return nome, f"postgres://postgres:test@127.0.0.1:{porta}/monitor_test?sslmode=disable"


def cobertura(repo: Path, dados: Path, tmp: Path, dsn: str | None) -> dict:
    mod = sh(["go", "list", "-m"], repo).strip()
    unit = tmp / f"{repo.name}-unit.out"
    sh(["go", "test", "-count=1", "-covermode=atomic", f"-coverprofile={unit}", "./..."], repo)
    pacotes_unit = perfil_cobertura(unit)

    pacotes_total = None
    if repo.name in INTEGRACAO and dsn:
        total = tmp / f"{repo.name}-total.out"
        sh(["go", "test", "-count=1", "-p=1", "-tags", "integration", "-covermode=atomic",
            "-coverpkg=./...", f"-coverprofile={total}", "./..."], repo,
           env={**ENV, "MONITOR_TEST_DSN": dsn})
        pacotes_total = perfil_cobertura(total)

    linhas = []
    for pacote in sorted(pacotes_unit):
        nome = pacote.removeprefix(mod).lstrip("/") or "."
        n, c = pacotes_unit[pacote]
        linha = [nome, n, c, pct(c, n)]
        if pacotes_total is not None:
            nt, ct = pacotes_total.get(pacote, [n, 0])
            linha += [ct, pct(ct, nt)]
        linhas.append(linha)
    cab = ["pacote", "statements", "cobertos_unit", "pct_unit"]
    if pacotes_total is not None:
        cab += ["cobertos_total", "pct_total"]
    escrever_csv(dados / f"{repo.name}-cobertura.csv", cab, linhas)

    n = sum(v[0] for v in pacotes_unit.values())
    c = sum(v[1] for v in pacotes_unit.values())
    r = {"statements": n, "cobertura_unit": pct(c, n)}
    if pacotes_total is not None:
        nt = sum(v[0] for v in pacotes_total.values())
        ct = sum(v[1] for v in pacotes_total.values())
        r["cobertura_total"] = pct(ct, nt)
    return r


def vulnerabilidades(repo: Path, dados: Path) -> dict:
    env = {**ENV, "GOTOOLCHAIN": f"go{go_version(repo)}"}
    out = sh(["govulncheck", "-format", "json", "./..."], repo, env=env)
    dec, i, osv_info, chamadas = json.JSONDecoder(), 0, {}, {}
    while i < len(out):
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            break
        obj, i = dec.raw_decode(out, i)
        if "osv" in obj:
            osv_info[obj["osv"]["id"]] = obj["osv"]
        f = obj.get("finding")
        if f and f.get("trace") and f["trace"][0].get("function"):
            chamadas[f["osv"]] = f["trace"][0].get("module", "")
    linhas = [[osv, mod, osv_info.get(osv, {}).get("summary", "")] for osv, mod in sorted(chamadas.items())]
    escrever_csv(dados / f"{repo.name}-vulnerabilidades.csv", ["osv", "modulo", "resumo"], linhas)
    stdlib = sum(1 for _, mod, _ in linhas if mod == "stdlib")
    return {"vulnerabilidades": len(linhas), "vulnerabilidades_stdlib": stdlib}


# --------------------------------------------------------------------------- relatório

def tabela(caption: str, label: str, colunas: str, cabecalho: list[str], linhas: list[list],
           nota: str = "") -> str:
    corpo = "\n".join("    " + " & ".join(str(c) for c in l) + r" \\" for l in linhas)
    nota_tex = f"\n  \\par\\smallskip\\footnotesize {nota}" if nota else ""
    return (f"\\begin{{table}}[htbp]\n  \\centering\\small\n  \\caption{{{caption}}}\n"
            f"  \\label{{{label}}}\n  \\begin{{tabular}}{{{colunas}}}\n    \\toprule\n"
            f"    {' & '.join(cabecalho)} \\\\\n    \\midrule\n{corpo}\n    \\bottomrule\n"
            f"  \\end{{tabular}}{nota_tex}\n\\end{{table}}\n")


def gerar_tex(it: str, saida: Path, resumo: dict, acopl: dict) -> None:
    cols = [CURTO[r] for r in REPOS]
    titulo = "baseline" if it == "baseline" else it

    linhas = [[tex(k)] + [resumo[r].get(f"lint_{k}", 0) for r in REPOS] for k in LINTERS]
    linhas.append([r"\textbf{Total}"] + [rf"\textbf{{{resumo[r]['lint_total']}}}" for r in REPOS])
    (saida / f"{it}-lint.tex").write_text(tabela(
        f"Issues do golangci-lint por linter ({titulo})", f"tab:{it}-lint",
        "l" + "r" * len(REPOS), ["Linter"] + cols, linhas,
        r"Configuração partilhada \texttt{lint/.golangci.yml}; inclui testes; sem deduplicação."))

    linhas = []
    for r in REPOS:
        s = resumo[r]
        linhas.append([CURTO[r], s["loc_producao"], s["loc_testes"], s["statements"],
                       f"{s['cobertura_unit']:.1f}",
                       f"{s['cobertura_total']:.1f}" if "cobertura_total" in s else "---"])
    texto = tabela(
        f"Dimensão e cobertura de testes ({titulo})", f"tab:{it}-cobertura", "lrrrrr",
        ["Repositório", "LOC prod.", "LOC testes", "Statements", r"Unit.\ (\%)", r"+ Integr.\ (\%)"],
        linhas, r"LOC: linhas não vazias. \emph{+ Integr.}: testes unitários e de integração "
                r"(PostgreSQL) com \texttt{-coverpkg=./...}.")
    central = WS / "monitor-platform" / "docs" / "metrics" / it / "dados" / "monitor-central-cobertura.csv"
    if central.exists():
        rows = [r for r in csv.DictReader(central.open()) if r["pacote"].startswith("internal/")]
        texto += "\n" + tabela(
            f"Cobertura por pacote do \\texttt{{monitor-central}} ({titulo})", f"tab:{it}-cobertura-central",
            "lrrr", ["Pacote", "Statements", r"Unit.\ (\%)", r"+ Integr.\ (\%)"],
            [[rf"\texttt{{{tex(r['pacote'].removeprefix('internal/'))}}}", r["statements"], r["pct_unit"],
              r.get("pct_total", "---")] for r in rows])
    (saida / f"{it}-cobertura.tex").write_text(texto)

    chaves = [("funcoes", "Funções"), ("ciclomatica_media", "Ciclomática média"),
              ("ciclomatica_max", "Ciclomática máxima"), ("ciclomatica_acima_limite", f"Ciclomática $>{LIMITE}$"),
              ("cognitiva_media", "Cognitiva média"), ("cognitiva_max", "Cognitiva máxima"),
              ("cognitiva_acima_limite", f"Cognitiva $>{LIMITE}$"),
              ("linhas_por_funcao_media", "Linhas/função (média)"),
              ("linhas_por_funcao_max", "Linhas/função (máx.)")]
    (saida / f"{it}-complexidade.tex").write_text(tabela(
        f"Complexidade das funções de produção ({titulo})", f"tab:{it}-complexidade",
        "l" + "r" * len(REPOS), ["Métrica"] + cols,
        [[n] + [resumo[r][k] for r in REPOS] for k, n in chaves],
        r"Ciclomática: McCabe (\texttt{tools/codemetrics}, igual ao gocyclo). "
        r"Cognitiva: gocognit. Excluem-se testes."))

    texto = ""
    for r in ["monitor-central", "monitor-remote"]:
        texto += tabela(
            f"Acoplamento entre pacotes do \\texttt{{{r}}} ({titulo})", f"tab:{it}-acoplamento-{CURTO[r]}",
            "lrrrrr", ["Pacote", "Ca", "Ce", "I", "A", "D"],
            [[rf"\texttt{{{tex(p['package'].removeprefix('internal/'))}}}", p["ca"], p["ce"],
              p["instability"] or "---", p["abstractness"], p["distance"] or "---"] for p in acopl[r]],
            r"Ca/Ce: acoplamento aferente/eferente dentro do módulo; I = Ce/(Ca+Ce); "
            r"A = interfaces/tipos; D = $|A+I-1|$ \cite{martin2002}.") + "\n"
    (saida / f"{it}-acoplamento.tex").write_text(texto)


def gerar_antes_depois(it: str, metrics_dir: Path, resumo: dict) -> None:
    base = metrics_dir / "baseline" / "resumo.csv"
    antes: dict[tuple[str, str], str] = {}
    if base.exists():
        antes = {(r["repositorio"], r["metrica"]): r["valor"] for r in csv.DictReader(base.open())}
    chaves = [("lint_total", "Issues de lint"), ("lint_depguard", "Violações de camadas"),
              ("ciclomatica_acima_limite", f"Funções ciclomática $>{LIMITE}$"),
              ("cognitiva_acima_limite", f"Funções cognitiva $>{LIMITE}$"),
              ("lint_dupl", "Blocos duplicados"), ("cobertura_unit", r"Cobertura unit.\ (\%)"),
              ("cobertura_total", r"Cobertura + integr.\ (\%)"),
              ("vulnerabilidades", "Vulnerabilidades alcançáveis"),
              ("distancia_media", "Distância média D")]

    def cel(r: str, k: str) -> str:
        agora = str(resumo[r].get(k, "---"))
        if it == "baseline" or (r, k) not in antes:
            return agora
        return f"{antes[(r, k)]} $\\to$ {agora}"

    titulo = "baseline" if it == "baseline" else f"baseline $\\to$ {it}"
    (metrics_dir / it / "metricas-codigo-antes-depois.tex").write_text(tabela(
        f"Métricas de código ({titulo})", "tab:metricas-antes-depois", "l" + "r" * len(REPOS),
        ["Métrica"] + [CURTO[r] for r in REPOS], [[n] + [cel(r, k) for r in REPOS] for k, n in chaves]))


def ambiente(saida: Path) -> None:
    linhas = [f"data: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}"]
    for r in REPOS:
        repo = WS / r
        ref = sh(["git", "rev-parse", "--short", "HEAD"], repo).strip()
        ramo = sh(["git", "branch", "--show-current"], repo).strip()
        sujo = " (com alterações por commitar)" if sh(["git", "status", "--porcelain"], repo).strip() else ""
        linhas.append(f"{r}: {ramo}@{ref}{sujo}, go.mod go {go_version(repo)}")
    linhas.append("go (medição): " + sh(["go", "version"], WS).strip())
    linhas.append("golangci-lint: " + sh(["golangci-lint", "version", "--short"], WS).strip())
    versao = sh(["govulncheck", "-version"], WS).splitlines()
    linhas.append("govulncheck: " + next((l for l in versao if l.startswith("Scanner")), "?"))
    linhas.append("govulncheck corre com GOTOOLCHAIN = versão do go.mod (a que o CI instala)")
    cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")), "?") if Path("/proc/cpuinfo").exists() else "?"
    linhas.append(f"cpu: {cpu} ({os.cpu_count()} threads)")
    (saida / "ambiente.txt").write_text("\n".join(linhas) + "\n")


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("iteracao", help="baseline | iter-N")
    ap.add_argument("--sem-integracao", action="store_true", help="não arranca o PostgreSQL em Docker")
    args = ap.parse_args()
    if not re.fullmatch(r"baseline|iter-\d+", args.iteracao):
        sys.exit("iteração deve ser 'baseline' ou 'iter-N'")
    for ferramenta in ["go", "golangci-lint", "govulncheck"] + ([] if args.sem_integracao else ["docker"]):
        if not shutil.which(ferramenta):
            sys.exit(f"falta {ferramenta} no PATH (ver README.md)")

    metrics_dir = PLATFORM / "docs" / "metrics"
    saida = metrics_dir / args.iteracao
    dados = saida / "dados"
    dados.mkdir(parents=True, exist_ok=True)

    contentor, dsn = (None, None) if args.sem_integracao else postgres_temporario()
    resumo: dict[str, dict] = {}
    acopl: dict[str, list[dict]] = {}
    try:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            for r in REPOS:
                repo = WS / r
                passo(r)
                s = linhas_de_codigo(repo)
                s.update(lint(repo, dados))
                s.update(funcoes(repo, dados, tmp))
                a, acopl[r] = acoplamento(repo, dados)
                s.update(a)
                s.update(cobertura(repo, dados, tmp, dsn))
                s.update(vulnerabilidades(repo, dados))
                resumo[r] = s
    finally:
        if contentor:
            subprocess.run(["docker", "rm", "-f", contentor], capture_output=True)

    escrever_csv(saida / "resumo.csv", ["repositorio", "metrica", "valor"],
                 [[r, k, v] for r in REPOS for k, v in resumo[r].items()])
    ambiente(saida)
    gerar_tex(args.iteracao, saida, resumo, acopl)
    gerar_antes_depois(args.iteracao, metrics_dir, resumo)
    passo(f"escrito em {saida.relative_to(PLATFORM)}")


if __name__ == "__main__":
    main()
