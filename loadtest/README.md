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
| `capacidade-1..3` | SC3 | a mesma carga acima da capacidade com 1, 2 e 3 instâncias atrás do nginx |
| `dashboard-30d` | SC4 | carga nominal sobre 31 dias de histórico, com as consultas do *dashboard*; duas fases, sem e com a retenção a 30 dias |

`capacidade-*` e `dashboard-30d` não fazem parte do conjunto por omissão (`dashboard-30d` gera ~330 M
registos: cerca de 1 h e ~150 GB de disco).

```sh
loadtest/correr.sh iter-6/sc4-antes dashboard-30d           # SC4 completo
HOSTS=50 DIAS_HISTORICO=2 DURACAO=2m loadtest/correr.sh ensaio dashboard-30d   # ensaio rápido
```

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
* **Histórico de SC4** (`historico.py`): 31 dias de estatísticas e erros dos hosts de carga, ao mesmo
  ritmo e com o mesmo perfil do k6, com os recibos de deduplicação que a ingestão grava; as linhas
  entram por ordem do tempo, com todos os hosts misturados, como na realidade. O PostgreSQL só corre
  sem limites durante a geração; a medição corre com os 2 vCPU / 4 GB e a cache do PostgreSQL fria.
  A primeira fase (`dashboard-30d.json`) corre sem retenção; a segunda (`dashboard-30d-retencao.json`),
  sobre os mesmos dados, com a retenção a 30 dias a cada minuto e o maior lote permitido (10.000). O
  k6 consulta, uma vez por segundo e à vez, as páginas e APIs do *dashboard* (p95 de cada uma) e
  `recolher.py` junta as execuções da retenção e os registos fora da janela antes e depois.
* **Resultados** (`recolher.py`): o k6 dá a visão do agente (latência, atraso, lotes não entregues);
  o Prometheus dá a do servidor (p95, CPU, memória, *pool* de ligações, ADR-0004); a base de dados
  confirma que tudo o que foi confirmado ficou gravado, sem duplicados. As contagens vêm do k6 e da
  base de dados: os contadores do Prometheus perdem o que acontece antes da primeira recolha.

As medições oficiais correm localmente, não no CI: os *runners* partilhados dão números com demasiado
ruído.
