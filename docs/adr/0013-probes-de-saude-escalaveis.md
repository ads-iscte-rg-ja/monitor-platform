# ADR-0013: *Probes* de saúde escaláveis: só os *hosts* devidos, espalhados no tempo

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability, Performance
* **Cenários relacionados:** AV2; MN2 (*heartbeat* dos *jobs*, ADR-0010); lacuna S1
* **Decisão do plano:** D7 (`../PLANO_MELHORIAS.md` §7.1)

## Contexto
Um *host* com *endpoint* de saúde é verificado pelo central (*Ping/Echo*): o *job* `host_health`, liderado por
uma instância (ADR-0007), corre a cada 30 s e percorre **todos** os *hosts* em páginas de 100, com 8 *probes* em
paralelo e 5 s de *timeout* cada (`internal/services/host_health.go`). Uma página só acaba quando acaba a sua
*probe* mais lenta, e o ciclo seguinte só começa quando o anterior acaba.

AV2: um *host* que deixa de responder gera o alerta `host_offline` em ≤ limiar + 60 s, **mesmo com 1.000
*hosts***. A regra de sistema tem o limiar a contar desde o início da primeira *probe* falhada
(`unavailable_since`), e o *job* de alertas avalia a cada 15 s. Os 60 s têm de cobrir o tempo até essa *probe*
começar (o período entre duas *probes* do mesmo *host*) mais uma avaliação: **período ≤ 45 s**.

**Medição** (`docs/metrics/iter-6/av2-antes.txt`; teste `TestAV2MeasureProbeCycle`, PostgreSQL real, 1.000
*hosts*, metade com um *endpoint* que nunca responde):

| Medida | Valor |
|---|---|
| Ciclo (= período entre *probes* do mesmo *host*) | **350,7 s** |
| Início da *probe* desde o início do ciclo | p50 175 s, máx 346 s |
| Pior atraso até ao alerta, além do limiar | **6 min 6 s** (alvo ≤ 60 s): **falha por um fator de 6** |
| Tempo de cada *host* em `unknown` por ciclo | 4 min 21 s |

Há mais dois efeitos do mesmo ciclo:
* `MarkHostsOffline` marca `unknown` um *host* com a última verificação mais velha do que 90 s
  (`HostHealthFreshness`), e `host_offline` deixa de o avaliar: durante mais de 4 min por ciclo, um *host* em
  baixo não pode disparar o alerta;
* o *heartbeat* do *job* (ADR-0010) só bate quando uma iteração acaba; com 350 s e um intervalo de 30 s, o
  líder responderia 503 no `/health/ready` a meio de cada ciclo (MN2 a dar um falso positivo).

## Decisão
1. **Cada *host* tem a sua próxima verificação** (`hosts.next_check_at`, migração 7, com um índice parcial para
   os *hosts* com *endpoint*). `NULL` é "devido já" (*hosts* novos ou com o *endpoint* alterado).
2. **O *job* acorda a cada 5 s e só verifica os *hosts* devidos** (`next_check_at <= agora`). Reclama-os com um
   `UPDATE … RETURNING` que marca já a verificação seguinte para daqui a **30 s ± 10 %** (*jitter*): as
   *probes* espalham-se no tempo em vez de saírem em rajada a cada 30 s, e uma iteração que se atrase não faz
   duas *probes* ao mesmo *host*.
3. **Concorrência configurável** (`HEALTH_CONCURRENCY`, 1–1.024, por omissão **128**) e sem páginas à espera da
   mais lenta: o *job* só reclama tantos *hosts* quantas as vagas livres, e cada *probe* começa logo que é
   reclamada. Um *host* lento ocupa uma vaga durante ≤ 5 s e não atrasa os outros.
4. **Prazo por iteração** igual ao intervalo (30 s): a iteração deixa de reclamar *hosts* nesse momento, espera
   pelas *probes* em curso (≤ 5 s) e acaba. Os que ficaram por verificar continuam devidos na iteração seguinte.
   O *heartbeat* continua registado com 30 s, e uma iteração dura no máximo 35 s, abaixo dos 60 s que o
   marcariam como parado.

**Pior caso com 1.000 *hosts*:** período ≤ 33 s (30 s + 10 %) + 5 s (o *job* acorda a cada 5 s) = 38 s, e
38 s + 15 s de avaliação = **53 s ≤ 60 s**. A capacidade chega: 500 *probes* em *timeout* a cada 30 s ocupam em
média 500 × 5 s / 30 s ≈ 83 das 128 vagas.

## Fundamentação teórica
* **Performance → *Introduce Concurrency*:** 128 *probes* em paralelo em vez de 8; as *probes* passam a esperar
  pela rede, não umas pelas outras.
* **Performance → *Schedule Resources*:** cada *host* tem a sua vez (`next_check_at`) e o *jitter* espalha a
  carga ao longo do intervalo, em vez de 1.000 pedidos de uma vez.
* **Performance → *Bound Execution Times*:** *timeout* por *probe* (5 s) e prazo por iteração (30 s).
* **Availability → *Ping/Echo*:** a tática que já existe; o que muda é que cumpre o prazo com 1.000 *hosts*.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Só aumentar a concorrência (128) e manter o ciclo por páginas | Com páginas de 100 à espera da mais lenta, um ciclo com metade em *timeout* dura ≈ 10 × 5 s = 50 s: falha AV2 e continua a disparar as *probes* em rajada |
| Uma *goroutine* por *host*, sem limite | 1.000 ligações de saída de uma vez, e o mesmo a cada 30 s; nenhum limite para a memória e os *sockets* com 10.000 *hosts* |
| Eliminar as *probes* e usar só o contacto do remote | Perde-se "host vivo, aplicação morta", que é a razão de ter um *endpoint* de saúde |
| *Probes* particionadas por várias instâncias (E7, hash por `host_id`) | Coordenação da partição; 1 instância chega com folga para 1.000 *hosts*. Gatilho abaixo |
| Agendar no Go (fila em memória) em vez de `next_check_at` | Perde-se o estado quando a liderança muda de instância (ADR-0007): o novo líder voltava a verificar todos de uma vez |

## Consequências
* **Positivas:** AV2 cumpre-se com 1.000 *hosts*; um *host* lento não atrasa os outros; a carga de saída é
  regular (≈ 33 *probes*/s com 1.000 *hosts*); os *hosts* deixam de passar a `unknown` entre verificações; o
  `/health/ready` deixa de dar falsos positivos com muitos *hosts* em baixo.
* **Negativas / *trade-offs*:**
  * Mais uma coluna e uma escrita por *probe* (o `UPDATE` que reclama), no PostgreSQL que já é o
    estrangulamento (ADR-0007, SC3). A 1.000 *hosts* são ≈ 33 escritas/s pequenas, num lote por iteração.
  * Até 128 *probes* gravam o resultado ao mesmo tempo e competem pelo *pool* de ligações; cada escrita é um
    `UPDATE` por chave primária. Fica medido no ciclo.
  * **Gatilho para E7:** se o período medido passar de 45 s (por exemplo, com 10.000 *hosts*, ou com a
    concorrência no máximo e o CPU do líder saturado), particionar as *probes* entre instâncias.

## Verificação
* **AV2** — o mesmo teste da linha de base (`TestAV2MeasureProbeCycle`), agora a correr o *job* durante 3 min
  com o relógio real, como em produção; o servidor de *endpoints* regista quando cada *host* recebe cada *probe*.
  Passa se o maior intervalo entre duas *probes* do mesmo *host*, mais 15 s, for ≤ 60 s.
* Testes unitários: só os devidos são verificados; as vagas limitam as *probes* em paralelo; o prazo para de
  reclamar; um *endpoint* alterado volta a ser devido; `HEALTH_CONCURRENCY` fora do intervalo é recusado.
* Teste de integração: a reclamação marca a verificação seguinte no intervalo com *jitter* e não devolve o mesmo
  *host* duas vezes.

**Resultado (21/11):** AV2 cumpre-se (`docs/metrics/iter-6/av2-depois.txt`), com o *job* a correr 3 min:

| Medida | Antes | Depois | Alvo |
|---|---|---|---|
| Intervalo entre *probes* do mesmo *host* (máx) | 350,7 s | **35,4 s** (p50 30,3 s) | ≤ 45 s |
| Pior atraso até ao alerta, além do limiar | 6 min 6 s | **50,4 s** | ≤ 60 s |
| Tempo em `unknown` por ciclo | 4 min 21 s | 0 | 0 |
| Iteração mais longa do *job* | 350,7 s | 20,2 s (a primeira, com os 1.000 devidos) | < 60 s (*heartbeat*) |
| *Probes* por segundo | — | 32,4 (no máximo 128 em simultâneo) | — |

O máximo de 35,4 s fica dentro da conta da decisão (≤ 38 s). As 128 vagas só enchem na primeira iteração, com
todos os *hosts* devidos ao mesmo tempo; depois, o *jitter* espalha-os. Lint do central: 54 → 53 (a
complexidade cognitiva de `Check` desceu de 26 para abaixo de 15); cobertura das linhas novas 90,3 %.

## Histórico
