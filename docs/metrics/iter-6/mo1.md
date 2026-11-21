# MO1: métrica de alerta nova (`buffer_quarantined`)

Cenário: *"pedido para alertar sobre uma métrica nova (ex.: quarentena > 0) → métrica implementada e testada sem
tocar no avaliador genérico; ≤ 1 pessoa-dia, ≤ 3 ficheiros Go + 1 migração"*. Linha de base (ADR-0008, antes
do D13): **7 sítios em 5 ficheiros e 3 camadas** por métrica nova.

Medido a 2026-11-20 sobre `monitor-central` `main` = d8fdaa4 com o D17 já feito (a tabela
`host_buffer_status`, que dá o dado, é do D17 e não conta para o MO1).

## O que mudou

| Ficheiro | Tipo | Alteração |
|---|---|---|
| `internal/alertmetric/buffer.go` | Go, novo | a estratégia (36 linhas, com a consulta) |
| `deployments/database/migrations/006_alert_buffer_quarantined.sql` | migração, nova | acrescenta o nome ao `CHECK` (6 linhas) |
| `deployments/database/embed.go` | Go | +3 linhas: embute a migração |
| `internal/database/migrate.go` | Go | +1 linha na lista de migrações; `SchemaVersion` 5 → 6 |
| `internal/alertmetric/metric_test.go` | teste | lista de nomes do registo; testes da estratégia nova |
| `internal/integration/alert_metrics_test.go` | teste | a métrica nova no teste de caracterização (PostgreSQL) |

**Não mudaram:** o avaliador (`services/alerts.go`), o repositório de alertas (`repositories/alerts.go`), o
*handler* e o formulário (a lista e a ajuda vêm do registo).

## Resultado

| Medida | Alvo | Medido | |
|---|---|---|---|
| Ficheiros Go de produção | ≤ 3 | 3 (1 novo + 2 com o registo da migração); antes do D13: 5 (3 com código da métrica + os mesmos 2) | cumpre |
| Migrações | 1 | 1 | cumpre |
| Alterações no avaliador genérico | 0 | 0 (antes: 6 sítios fora da métrica e da migração, mais 1 modelo HTML) | cumpre |
| Camadas tocadas | — | 1 (`alertmetric`) + registo da migração; antes 3 | |
| Tempo | ≤ 1 pessoa-dia | 1 min 18 s de relógio (19:05:09 → 19:06:27 UTC), do primeiro ficheiro aberto aos testes de integração verdes | cumpre; ver nota |

**Nota sobre o tempo:** a alteração foi feita com um assistente de programação; o tempo medido não é o de uma
pessoa sem assistência. O que sustenta o alvo de ≤ 1 pessoa-dia é a dimensão: 36 linhas de Go num ficheiro
novo, 6 de SQL e 4 de registo, seguindo um modelo (`errors.go`) que já existe.

**Custo escondido encontrado:** `embed.go` e `migrate.go` mudam em qualquer migração, não só nas de métricas.
Sem eles, o MO1 seria 1 ficheiro Go. Um *runner* que descobrisse as migrações pelo nome do ficheiro tiraria esses
dois; não se fez, porque o MO1 já cumpre e a ordem explícita das migrações é uma garantia útil.

## Testes que provam a métrica

```
cd monitor-central && go test ./internal/alertmetric/
cd monitor-central && MONITOR_TEST_DSN=... go test -tags integration \
  -run 'TestEveryAlertMetricIsEvaluatedFromTheDatabase|TestRegisteredMetricsMatchTheDatabaseConstraint' ./internal/integration
```
Saída em [`mn1-mn2.txt`](mn1-mn2.txt).
