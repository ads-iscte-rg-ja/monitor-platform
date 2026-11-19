# Testes de carga

Cenários k6 que simulam 1.000 remotes contra a ingestão gRPC do central (plano §7, D10). Dão as
*response measures* dos cenários de escalabilidade e geram as tabelas do relatório.

```sh
loadtest/correr.sh iter-3                      # medição completa (~1 h)
HOSTS=50 DURACAO=1m DURACAO_RECUPERACAO=2m loadtest/correr.sh ensaio nominal   # ensaio rápido
loadtest/tabelas.py iter-5 --antes iter-3      # tabelas antes/depois
```

Os resultados ficam em `docs/metrics/<iteração>/carga/` (um JSON por medição e `ambiente.txt`) e as
tabelas em `docs/metrics/<iteração>/carga-*.tex` (`make dados ITER=<iteração>` copia-as para o relatório).

## Medições

| Medição | Cenário | O que mede |
|---|---|---|
| `nominal` | SC1 | 1.000 hosts durante 10 min com o perfil misto de logs: p95 da ingestão, CPU, atraso, perdas |
| `nominal-x2`, `nominal-x5` | sensibilidade | o mesmo com 2× e 5× a taxa de logs (o perfil é uma hipótese) |
| `noisy-neighbour` | SC5 | 1 % dos hosts em rajada de 200 logs/s durante 2 min: atraso dos restantes |
| `recovery-storm` | SC2 | 1 h de *backlog* em todos os hosts ao mesmo tempo: tempo de absorção, dashboard, perdas |

`scale-out` (SC3) só faz sentido depois de D8 (várias instâncias sem *jobs* duplicados).

## Como funciona

* **Ambiente próprio** (`compose.yaml`, projeto `monitor-carga`): central, PostgreSQL 16 e Prometheus,
  construídos a partir de `../../monitor-central`. Os limites da medição estão no ficheiro: central e
  PostgreSQL com **2 vCPU e 4 GB** cada; o k6 não tem limites, porque não é ele que está a ser medido.
  Cada medição recria o ambiente do zero (base de dados vazia, central acabado de arrancar).
* **Hosts** (`provisionar.py`): N hosts com chaves aleatórias, registados por SQL com o mesmo digest
  HMAC que o central usa. O perfil de cada host vem do índice: em cada 100, 1 em rajada, 4 ruidosos,
  25 normais e 70 silenciosos.
* **Agentes** (`k6/ingestao.js`): cada VU é um host e comporta-se como o remote — estatísticas a cada
  30 s, erros a cada 10 s, lotes de até 100 registos, novas tentativas com *backoff* nas falhas
  transitórias e paragem nas definitivas. O contrato vem do `.proto` do `monitor-api`.
* **Atraso** (`atraso_central`): do primeiro envio de um lote à confirmação, com as novas tentativas. É
  o atraso que o central acrescenta; o intervalo de recolha do agente (até 10 s) é fixo por desenho e
  fica de fora.
* **Resultados** (`recolher.py`): o k6 dá a visão do agente (latência, atraso, lotes não entregues);
  o Prometheus dá a do servidor (p95, CPU, memória, *pool* de ligações, ADR-0004); a base de dados
  confirma que tudo o que foi confirmado ficou gravado, sem duplicados. As contagens vêm do k6 e da
  base de dados: os contadores do Prometheus perdem o que acontece antes da primeira recolha.

As medições oficiais correm localmente, não no CI: os *runners* partilhados dão números com demasiado
ruído.
