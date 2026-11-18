# Testes de carga

**Estado:** por implementar (plano §7, D10; iterações 2–4).

Cenários k6 que simulam remotes contra a API de ingestão do central. Fornecem as *response measures*
dos cenários de escalabilidade e as tabelas do relatório (`report/gerado/`).

| Cenário | QA | O que mede |
|---|---|---|
| `nominal` | SC1 | 1.000 hosts, perfil misto de logs: p95, throughput, % erros, lag |
| `recovery-storm` | SC2 | 1.000 hosts com 1 h de backlog ao mesmo tempo: tempo de absorção, 429, dashboard |
| `noisy-neighbour` | SC5 | 1% dos hosts em rajada: lag dos hosts normais |
| `scale-out` | SC3 | throughput com 1, 2 e 3 instâncias do central |

As medições oficiais correm localmente com limites fixos nos containers (central: 2 vCPU / 4 GB),
não no CI: os runners partilhados dão números com demasiado ruído.
