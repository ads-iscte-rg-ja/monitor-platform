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

## Por escrever

**Retroativos** (decisões que já existem no código):
* Monólito em camadas no central (handlers → services → repositories)
* Store-and-forward em SQLite no remote, com recibos de deduplicação no central
* Outbox transacional para email
* Chaves de host com digest HMAC-SHA256
* Jobs de fundo dentro do processo central

**Novas** (decisões D2–D19 de `../PLANO_MELHORIAS.md` §7).
