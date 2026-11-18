# Medições

Resultados de cada medição, por iteração, para o "antes/depois" do relatório (cap. 7).

```sh
scripts/medir.py baseline        # iteração 0 (antes de qualquer alteração)
scripts/medir.py iter-1          # depois da iteração 1; compara com a baseline
cd report && make dados ITER=iter-1 && make
```

Requer `go`, `golangci-lint`, `govulncheck` (versões do CI) e `docker` (PostgreSQL temporário para os
testes de integração do central; `--sem-integracao` para saltar). Demora ~40 s.

| Ficheiro | Conteúdo |
|---|---|
| `<iter>/resumo.csv` | uma linha por (repositório, métrica): é daqui que sai o "antes/depois" |
| `<iter>/ambiente.txt` | commits medidos, versões das ferramentas, CPU |
| `<iter>/dados/*.csv` | dados brutos: issues do lint, métricas por função, acoplamento, cobertura por pacote, vulnerabilidades |
| `<iter>/<iter>-*.tex`, `metricas-codigo-antes-depois.tex` | tabelas LaTeX que o `make dados` copia para `report/gerado/` |

O govulncheck corre com a versão de Go do `go.mod`, a mesma que o CI instala (`GOTOOLCHAIN`).
