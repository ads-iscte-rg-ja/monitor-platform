# Registo de decisões arquiteturais (ADR)

Processo em [ADR-0001](0001-registar-decisoes-com-adrs.md); modelo em [0000-modelo.md](0000-modelo.md).

| ADR | Título | Estado | QA |
|---|---|---|---|
| [0001](0001-registar-decisoes-com-adrs.md) | Registar as decisões arquiteturais em ADRs | Aceite | Modifiability |
| [0002](0002-repositorio-monitor-platform.md) | Repositório `monitor-platform` para CI partilhado e artefactos transversais | Aceite | Modifiability |
| [0003](0003-contrato-ingestao-grpc.md) | Contrato de ingestão em gRPC, num repositório `monitor-api` versionado | Aceite | Modifiability, Interoperability |
| [0004](0004-metricas-e-logs-estruturados.md) | Medir primeiro: métricas Prometheus num listener interno e logs estruturados | Aceite | Monitorability |
| [0005](0005-escritas-em-lote.md) | Escritas em lote na ingestão e na resolução de alertas | Aceite | Scalability |
| [0006](0006-controlo-de-admissao.md) | Controlo de admissão na ingestão, com ligações reservadas para o resto do central | Aceite | Scalability, Availability |
| [0007](0007-central-escalavel-horizontalmente.md) | Central com várias instâncias: liderança por *job*, limites partilhados e balanceador | Aceite | Scalability, Availability, Security |
| [0008](0008-metricas-de-alerta-como-strategy.md) | Métricas de alerta como Strategy, com um registo como Simple Factory | Aceite | Modifiability |
| [0009](0009-buffer-do-remote-com-limite.md) | *Buffer* do remote com limite e descarte por severidade | Aceite | Availability, Performance |
| [0010](0010-estado-do-buffer-e-health-ready.md) | Estado do *buffer* reportado ao central; `/health/live` e `/health/ready` | Aceite | Monitorability, Availability |
| [0011](0011-remote-retoma-sem-reinicio.md) | O remote retoma a entrega sem reinício | Aceite | Availability |
| [0012](0012-higiene-e-testes-ponta-a-ponta.md) | Higiene dos repositórios e testes ponta a ponta em Compose | Aceite | Testability, Availability |
| [0013](0013-probes-de-saude-escalaveis.md) | *Probes* de saúde escaláveis: só os *hosts* devidos, espalhados no tempo | Aceite | Availability, Performance |
| [0014](0014-handlers-testaveis-relogio-e-fuso.md) | *Handlers* testáveis com interfaces mínimas; relógio e fuso horário injetados | Aceite | Testability |
| [0015](0015-fonte-unica-das-regras-de-dominio.md) | Uma fonte única por repositório para os níveis de log e o endereço do central | Aceite | Modifiability |

## Por escrever

**Retroativos** (decisões que já existem no código):
* Monólito em camadas no central (handlers → services → repositories)
* Store-and-forward em SQLite no remote, com recibos de deduplicação no central
* Outbox transacional para email
* Chaves de host com digest HMAC-SHA256
* Jobs de fundo dentro do processo central

**Novas** (decisões D2–D19 de `../PLANO_MELHORIAS.md` §7).
