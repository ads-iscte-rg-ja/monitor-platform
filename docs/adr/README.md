# Registo de decisões arquiteturais (ADR)

Processo em [ADR-0001](0001-registar-decisoes-com-adrs.md); modelo em [0000-modelo.md](0000-modelo.md).

| ADR | Título | Estado | QA |
|---|---|---|---|
| [0001](0001-registar-decisoes-com-adrs.md) | Registar as decisões arquiteturais em ADRs | Aceite | Modifiability |
| [0002](0002-repositorio-monitor-platform.md) | Repositório `monitor-platform` para CI partilhado e artefactos transversais | Aceite | Modifiability |

## Por escrever

**Retroativos** (decisões que já existem no código):
* Monólito em camadas no central (handlers → services → repositories)
* Store-and-forward em SQLite no remote, com recibos de deduplicação no central
* Outbox transacional para email
* Chaves de host com digest HMAC-SHA256
* Jobs de fundo dentro do processo central

**Novas** (decisões D2–D19 de `../PLANO_MELHORIAS.md` §7).
