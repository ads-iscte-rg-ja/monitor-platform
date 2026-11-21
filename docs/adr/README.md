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
| [0016](0016-endurecimento-por-checklist-asvs.md) | Endurecimento por *checklist* (ASVS 5.0 N1): cabeçalhos, CSP, Tailwind local e guarda SSRF | Aceite | Security |
| [0017](0017-consultas-limitadas-e-bulkhead-do-dashboard.md) | Com 30 dias de dados, consultas do *dashboard* com custo limitado e um *bulkhead* no *pool*; particionar só se a retenção o exigir | Aceite | Scalability, Performance |
| [0018](0018-postgresql-base-de-dados-unica-do-central.md) | PostgreSQL como base de dados única do central, para a telemetria e para o resto | Aceite (retroativo) | Scalability, Availability, Modifiability |
| [0019](0019-estilo-arquitetural.md) | Estilo arquitetural: agentes *store-and-forward* e um central monolítico em camadas, replicado sobre uma base de dados partilhada | Aceite (retroativo) | todos |
| [0020](0020-store-and-forward-em-sqlite-no-remote.md) | *Store-and-forward* em SQLite no remote, com entrega *at-least-once* e recibos de deduplicação no central | Aceite (retroativo) | Availability |
| [0021](0021-sdk-escreve-no-buffer-do-remote.md) | O SDK escreve diretamente no *buffer* SQLite do remote, cujo esquema pertence ao remote | Aceite (retroativo) | Availability, Modifiability |
| [0022](0022-outbox-transacional-para-os-emails.md) | *Outbox* transacional para os emails dos alertas | Aceite (retroativo) | Availability |
| [0023](0023-chaves-dos-hosts-com-digest-hmac.md) | Chaves dos *hosts* aleatórias de 256 bits, guardadas como *digest* HMAC-SHA256 | Aceite (retroativo) | Security, Performance |

## Por escrever

**Retroativos:** nenhum por escrever (o ADR-0019 cobre o monólito em camadas, os *jobs* dentro do processo, Go
e a interface feita no servidor).

**Novas:** nenhuma (todas as decisões D1–D20 do plano têm ADR).
