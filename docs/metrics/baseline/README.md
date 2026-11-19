# Baseline (iteração 0): conclusões

Medido a 18/11/2026 sobre `ci/setup` dos 4 repositórios. O código é igual ao da `main`: essa branch só acrescenta ficheiros de CI. Detalhes em `ambiente.txt`, números em `resumo.csv`.
Gerado com `scripts/medir.py baseline`.

| | central | remote | SDK | hello-world |
|---|---:|---:|---:|---:|
| LOC produção / testes | 6604 / 2077 | 1902 / 1518 | 131 / 0 | 74 / 133 |
| Issues de lint | 66 | 29 | 4 | 1 |
| Violações de camadas (depguard) | 1 | 0 | 0 | 0 |
| Funções ciclomática > 15 / cognitiva > 15 | 5 / 10 | 3 / 6 | 0 / 0 | 0 / 1 |
| Cobertura unitária | 25,9 % | 68,0 % | 0 % | 56,8 % |
| Cobertura unitária + integração | 40,3 % | — | — | — |
| Vulnerabilidades alcançáveis (stdlib) | 52 (50) | 37 (37) | 1 (1) | 1 (1) |

## O que os números dizem

1. **Arquitetura: só uma violação de camadas.** `internal/handlers/health.go` importa `internal/database`.
   As camadas handler → service → repository estão, no geral, respeitadas. A correção é um
   `HealthService`, e passa a existir uma regra executável a impedir que volte a acontecer (plano D1/D15).

2. **A complexidade está concentrada em poucas funções.** São as candidatas a refatoração (plano M-*):

   | Função | Linhas | Ciclomática | Cognitiva |
   |---|---:|---:|---:|
   | central `(DB).Migrate` | 99 | 30 | 46 |
   | remote `deliverBatch` | 57 | 14 | 33 |
   | central `(HostHealthService).Check` | 46 | 12 | 26 |
   | central `seed.Demo` | 47 | 12 | 24 |
   | central `validateAlert` | 51 | 23 | 23 |
   | central `(AlertsService).EvaluateMetricAlerts` | 38 | 11 | 23 |

   Em média as funções são simples (ciclomática ≈ 4 no central). O problema está nos extremos, não em
   todo o código, e é por isso que o gate se aplica a código novo e a funções acima do limite.

3. **A cobertura do central esconde uma lacuna na camada HTTP.** `services` tem 71 %, mas
   `handlers` fica em 16 % e `server` em 0 %, mesmo somando os testes de integração. Os
   `repositories` só são exercitados pela integração (0 % → 39 %). Isto justifica medir a cobertura com
   integração (`-coverpkg`) e os testes E2E (D15). O SDK não tem nenhum teste.

4. **As vulnerabilidades vêm quase todas da versão de Go declarada.** Os `go.mod` fixam `go 1.25.0`
   e o CI instala exatamente essa versão. A imagem Docker de produção (`golang:1.25-alpine`) já usa o
   último patch, por isso em produção o risco é menor do que o número sugere. Mesmo assim, o CI tem de
   medir o que se declara.
   **Ação (iteração 1):** acrescentar `toolchain go1.25.<último>` aos 4 `go.mod`. Com isso, o
   setup-go e o govulncheck passam a usar essa versão.
   Há **2 vulnerabilidades reais de dependências** no central (`golang.org/x/text`: GO-2026-5970 e
   GO-2026-6629). **Ação:** atualizar o `x/text`. O Dependabot também o vai propor.

   **Correção (19/11, ao executar a iteração 1):** a premissa sobre a imagem de produção estava
   errada. O Go só suporta as duas últimas versões (1.26 e 1.27), e parte das correções só existe na
   1.26: a linha 1.25, incluindo o último patch, continua vulnerável. Ação aplicada: `toolchain
   go1.27.4` nos 4 `go.mod` e imagem `golang:1.27.4-alpine`; `x/text` v0.41.0 (a menor versão que
   corrige as duas, mantendo `go 1.25.0`). Resultado em `../iter-1/`.

5. **gosec: dois prováveis falsos positivos para documentar.** O `G201` em `repositories/retention.go:55`
   formata SQL, mas só com constantes da aplicação; os valores vão como parâmetros `$1`/`$2`. O `G703` em
   `templating/pages/pages.go:135,140` já está mitigado com `filepath.Rel` e uma verificação de
   ficheiro regular. **Ação:** marcar cada um com `//nolint:gosec // <motivo>`, para que a exceção
   fique escrita e revista, em vez de ficar ruído permanente no lint. Os restantes `gosec` são
   sobretudo `G104` (erros ignorados), que coincidem com os do `errcheck`.

6. **Acoplamento.** `server` tem Ce = 10 e I = 0,91: é a raiz de composição, por isso é esperado.
   `services` tem abstração 0,47 porque declara as interfaces de que precisa, aplicando DIP. É o pacote mais perto
   da sequência principal (D = 0,10). `database` tem Ca = 8. Fora `repositories`, os pacotes que
   dependem dele (handlers, seed e os comandos) são os pontos a rever quando a BD mudar
   (particionamento, D9).

## Nota sobre a medição

O golangci-lint deduplica por omissão os issues que caem na mesma linha (`uniq-by-line`). Como o
`gocognit` e o `gocyclo` apontam ambos para a assinatura da função, o `gocyclo` ficava escondido.
Com a deduplicação ativa o central dava 61 issues; com ela desligada dá 66. A configuração partilhada
desliga-a, porque estas contagens são métricas do relatório.

## SonarQube Cloud

`sonar.csv`: medidas da primeira análise do SonarQube Cloud ao código da baseline (commit e data da
análise em cada linha), obtidas da API `measures/search_history`. Só regras da própria ferramenta: o
relatório do golangci-lint ainda não era importado. Triagem dos 8 issues do central no relatório, §5.4.
