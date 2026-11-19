# ADR-0005: Escritas em lote na ingestão e na resolução de alertas

* **Estado:** Aceite
* **Data:** 2026-11-19
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Scalability (via Performance)
* **Cenários relacionados:** SC2 (recuperação), SC1; lacunas S2, S3
* **Decisão do plano:** D5 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
A baseline de carga (iteração 3, `docs/metrics/iter-3/carga/`) mostrou que o único cenário que falha é a
recuperação (SC2): o *dashboard* fica com p95 ≥ 10 s enquanto 1.000 hosts entregam o *backlog*. O CPU do central
não passa de 30 %; o recurso esgotado é o *pool* de ligações à base de dados (25 de 25, ~11.200 esperas).

Cada lote de ingestão ocupa uma ligação durante toda a transação, e a transação faz **dois *statements* por
registo** (o recibo de deduplicação e o registo): um lote de 100 são ~200 idas à base de dados com a ligação
presa (`monitor-central/internal/repositories/monitoring.go`). O *job* de alertas faz um UPDATE por cada regra
não violada, a cada 15 s (S3): até 400 por segundo com 1.000 hosts e ~6 regras por host.

## Decisão
1. **Ingestão: três *statements* por lote**, na mesma transação, independentemente do tamanho do lote:
   * os recibos de todo o lote com um `INSERT … SELECT … FROM unnest($fontes) ON CONFLICT DO NOTHING
     RETURNING`, que diz que registos são novos e devolve o identificador já atribuído aos repetidos;
   * os registos novos com um `INSERT … SELECT … FROM unnest(...)` de *arrays* por coluna;
   * a atualização do `last_seen_at` do host.

   A idempotência e a atomicidade mantêm-se: dados e recibos continuam na mesma transação, e um reenvio
   devolve os mesmos identificadores. Num conflito com uma transação concorrente que ainda não era visível,
   uma segunda leitura (só desses registos) obtém o identificador, como antes.
2. **Alertas: um UPDATE por ciclo** que resolve de uma vez os eventos abertos de todos os pares
   (alerta, host) não violados, passados como *arrays*.

## Fundamentação teórica
* **Performance → *Reduce Overhead*** e ***Increase Resource Efficiency***: menos idas à base de dados por
  unidade de trabalho; cada ligação fica presa menos tempo, o que aumenta o débito do mesmo *pool*.
* **Modifiability → *Encapsulate***: a mudança fica dentro do repositório; a interface usada pelos serviços não
  muda, e os testes de integração existentes (idempotência, *rollback* conjunto, concorrência) validam-na.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| `COPY` | É o mais rápido, mas não suporta `ON CONFLICT` nem devolve identificadores, de que o *ack* precisa |
| Aumentar o *pool* de ligações | Adia o problema e passa-o para o PostgreSQL (`max_connections` = 100, partilhado por todas as instâncias de D8) |
| *Cache*/fila em memória antes da BD | Arrisca perder dados confirmados ao agente (AV1); a fila durável é a evolução E1, com gatilho |
| *Prepared statement* por registo (já existia nos erros) | Poupa o *parse*, mas não as idas à base de dados |

## Consequências
* **Positivas:** o tempo de cada transação deixa de crescer com o número de registos; o *pool* serve mais
  pedidos por segundo; o *job* de alertas deixa de gerar centenas de UPDATE por segundo.
* **Negativas / trade-offs:** SQL mais complexo (CTE com `unnest` e `RETURNING`); mitigado por ficar isolado no
  repositório e coberto pelos testes de integração. Os carimbos temporais passam como texto RFC 3339 para o
  *array* (o driver não converte `[]time.Time`), com *cast* explícito no SQL.

## Verificação
* Testes de integração existentes (deduplicação por host, *replay*, *rollback* de dados e recibos juntos,
  recibos concorrentes) e um novo para um lote com registos novos e repetidos misturados.
* Carga (`loadtest/correr.sh iter-4`, comparado com `iter-3`): p95 da ingestão e esperas por ligação em SC2.
