# ADR-0004: Medir primeiro — métricas Prometheus num listener interno e logs estruturados

* **Estado:** Aceite
* **Data:** 2026-11-19
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Monitorability (habilita Scalability)
* **Cenários relacionados:** SC1–SC5 (medidas dos testes de carga), MN2; lacunas S8, A3
* **Decisão do plano:** D4 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
O central não expõe nenhuma métrica de execução (lacuna S8). As medidas dos cenários de escalabilidade
(p95 da ingestão, rejeições por sobrecarga, atraso de ingestão, CPU, uso do pool de ligações) não se
conseguem observar no servidor, só do lado do cliente de carga. Sem elas não se distingue *onde* está o
estrangulamento, e as decisões D5–D8 não se podem avaliar. Os logs são texto livre
(`log.Logger`), sem identificador de pedido nem de host (lacuna A3): não se filtram nem se correlacionam.

Na primeira versão do plano o Prometheus estava adiado. A decisão mudou porque o ASR mudou: a
escalabilidade passou a (H,H) e passou a precisar de medição (ADD, passo 4: rever o que falta tratar).

## Decisão
1. **Métricas Prometheus** (`prometheus/client_golang`, registo próprio, não o global) no pacote
   `internal/observability`:
   | Métrica | Tipo | Para |
   |---|---|---|
   | `monitor_ingest_request_duration_seconds{method,code}` | histograma | p95/p99 da ingestão e taxa de rejeições por código gRPC (SC1, SC2, SC5) |
   | `monitor_ingest_records_total{kind,outcome}` | contador | registos novos, duplicados e rejeitados |
   | `monitor_ingest_batch_records{kind}` | histograma | tamanho dos lotes |
   | `monitor_ingest_lag_seconds{kind}` | histograma | atraso de ingestão (`agora − momento da recolha`) |
   | `monitor_http_request_duration_seconds{route,method,status}` | histograma | latência do dashboard (SC2, SC4) |
   | `monitor_job_duration_seconds{job}`, `monitor_job_failures_total{job}`, `monitor_job_last_success_timestamp_seconds{job}` | histograma, contador, gauge | duração e saúde dos *jobs* de fundo (MN2) |
   | `monitor_email_outbox_pending` | gauge | backlog de notificações |
   | `go_sql_*` | gauges/contadores | pool de ligações à base de dados (S4) |
   | `go_*`, `process_*` | | memória, *goroutines*, CPU do processo (SC1) |

   As *labels* têm cardinalidade limitada: rotas pelo padrão (`/hosts/{id}`) e não pelo caminho, e nunca
   o host como *label* (com 1.000 hosts seriam 1.000 séries por métrica).
2. **`/metrics` num listener separado** (`METRICS_ADDR`, por omissão `127.0.0.1:9464`), fora do router
   do dashboard: nunca passa pelo proxy público nem pela sessão. Vazio desliga as métricas.
3. **Logs estruturados com `log/slog`** em JSON (`LOG_FORMAT=json|text`, `LOG_LEVEL`). Os pedidos HTTP
   são registados com `request_id`, rota, estado e duração; os pedidos de ingestão gRPC que falham, com
   `host_id`, método e código (os bem-sucedidos só em `debug`, para 1.000 hosts não gerarem dezenas de
   linhas por segundo). O `log.Logger` existente passa a escrever através do mesmo *handler*, para todas
   as linhas saírem no mesmo formato sem alterar cada chamada.
4. **Perfil Compose `observability`** (Prometheus + Grafana com a fonte de dados já configurada), só para
   os testes de carga e demonstrações; não arranca por omissão.

## Fundamentação teórica
* **Monitor** (availability) e **Monitorability** (slide 03): o sistema observa-se a si próprio.
* **Record/Playback** (testability): os testes de carga ficam com as medidas do lado do servidor.
* **Limit Exposure** (security): as métricas não estão no listener público.
* *Generate and test* (slide 06): sem medição no servidor, o "teste" de cada hipótese de escala fica
  incompleto.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| OpenTelemetry completo (traces, métricas, coletor) | Mais infraestrutura do que o necessário para 1.000 hosts num só serviço; fica no plano de evolução (E6), com o gatilho "diagnosticar latência entre serviços" |
| Só medir do lado do k6 | Dá a latência vista pelo cliente, mas não *onde* está o estrangulamento (BD, CPU, jobs) |
| `/metrics` no router do dashboard | Ficaria atrás do proxy público e misturado com a sessão; exigiria autenticação própria |
| Host como *label* | 1.000 hosts × métricas = cardinalidade que degrada o próprio Prometheus; o detalhe por host vai para os logs |
| Reescrever todas as chamadas a `log.Printf` | Muitas alterações sem valor arquitetural; o `log.Logger` sobre `slog` dá o mesmo formato |

## Consequências
* **Positivas:** as medidas de SC1–SC5 passam a observar-se no servidor; os logs filtram-se por pedido e
  por host; o custo é nulo quando ninguém lê `/metrics`.
* **Negativas / trade-offs:** cada pedido paga a atualização de alguns contadores (ordem dos
  microssegundos); a métrica do outbox faz uma consulta à BD por *scrape* (a cada 15 s, com *timeout*);
  as linhas antigas de `log.Printf` saem em JSON mas só com a mensagem, sem campos estruturados.

## Verificação
* Teste que faz *scrape* de `/metrics` e encontra as métricas acima, com os valores esperados depois de
  pedidos de ingestão (aceites, duplicados, rejeitados) e de uma execução de *job* falhada.
* Durante os testes de carga (D10), as medidas de SC1–SC5 são lidas do Prometheus.
