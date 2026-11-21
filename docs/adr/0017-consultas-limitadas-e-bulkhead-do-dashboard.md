# ADR-0017: Com 30 dias de dados, consultas do *dashboard* com custo limitado e um *bulkhead* no *pool*; particionar só se a retenção o exigir

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Scalability, Performance
* **Cenários relacionados:** SC4; SC1 (a ingestão não pode degradar); lacuna S7
* **Decisão do plano:** D9 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
SC4: com **30 dias de dados de 1.000 *hosts*** e a retenção ativa, o *dashboard* responde com **p95 < 1 s** e a
retenção **não degrada a ingestão**. O plano previa particionar `machine_stats` e `error_logs` por dia e fazer a
retenção com `DROP PARTITION`. A regra do roteiro era medir primeiro e particionar só se SC4 falhasse.

**Medição** (`docs/metrics/iter-6/sc4-antes/`; `loadtest/correr.sh iter-6/sc4-antes dashboard-30d`).
`loadtest/historico.py` gera 31 dias ao ritmo e com o perfil de logs do k6: **89,3 M estatísticas, 238,8 M
erros e 328,1 M recibos, 143 GB**. Por cima disso corre a carga nominal (SC1) durante 10 min, com uma consulta
do *dashboard* por segundo, à vez por 7 páginas e APIs. Há duas fases sobre os mesmos dados: sem retenção, e
com a retenção a 30 dias a cada minuto, com o maior lote permitido (10.000). O central e o PostgreSQL têm
2 vCPU / 4 GB cada.

| Medida | Sem retenção | Com retenção | Alvo |
|---|---|---|---|
| p95 das 7 consultas do *dashboard* | **29–74 s** | **33–74 s** | < 1 s |
| p95 da ingestão (agente) | 1.594 ms | 2.182 ms | < 300 ms (SC1) |
| Pedidos de ingestão rejeitados por sobrecarga | 58 % | 61 % | — |
| Registos confirmados em 10 min (esperados ≈ 73.000) | 11.008 | 10.489 | — |
| Esperas por uma ligação do *pool* (25/25 em uso) | 9.057 | 9.874 | — |
| Execuções da retenção: duração média / p95 | — | 7,4 s / 27 s (*timeout*: 30 s) | — |
| Registos expirados: variação por hora | +441 mil (só envelhecem) | −722 mil | ≤ 0 |

**SC4 falha nas duas partes, e a ingestão falha logo na fase sem retenção.** Não se perdeu nenhum registo (0
lotes perdidos, 0 duplicados): o que não entrou ficou nos agentes, por entregar. Para separar a causa, cada
consulta foi medida **isolada**, com o sistema parado, nos mesmos limites (`EXPLAIN (ANALYZE, BUFFERS)`):

| Consulta (página) | Tempo | Porquê |
|---|---|---|
| CPU médio do último registo de cada *host* (`/summary`, `/dashboard`) | **55,0 s** | `DISTINCT ON (host_id)` percorre os 89 M de estatísticas |
| Nomes de aplicação distintos (`/errors`) | **17,1 s** | `SELECT DISTINCT` percorre os 239 M de erros |
| Total de erros, sem filtro (`/errors`) | **13,3 s** | `COUNT(*)` da tabela inteira |
| Métricas de 1 mês de um *host* (`/metrics?range=1m`) | **5,3 s** | 86 mil linhas espalhadas pelo disco: uma leitura aleatória do *heap* por linha |
| Total de erros de um *host* ruidoso (`/errors?host_id=`) | 1,3 s | `COUNT(*)` de 2,7 M linhas |
| Erros de hoje (`/summary`) | 0,97 s, e a crescer ao longo do dia | `COUNT(*)` de ~5 M linhas (7,7 M ao fim do dia) |
| Último registo de cada *host* (`/hosts`) | 88 ms | *lateral* sobre o índice `(host_id, collected_at)` |
| Métricas de 24 h | 16 ms | índice |
| Lista de erros, 20 linhas | 0,6 ms | índice |

**O mecanismo:** quatro consultas têm um custo proporcional ao volume total, não ao que mostram. Nenhuma
tem um limite temporal que o particionamento pudesse usar. Cada uma prende uma ligação durante dezenas de
segundos e, com uma consulta por segundo, ocupam as 25 ligações. A partir daí tudo espera: as consultas de
16 ms, a ingestão e o `/health/ready` (o *healthcheck* do Compose marcou o central como `unhealthy`). O ADR-0006
limita a ingestão a 60 % do *pool*, mas nada limita o *dashboard*.

A retenção, por seu lado, acompanha o débito: remove ~1,16 M registos por hora, 2,6 vezes o que entra. O seu
efeito na ingestão (+37 % no p95) não se separa da saturação que o *dashboard* já provoca.

**Ressalva da medição:** com respostas de 60 s, o k6 chega a ter 60 consultas em curso, mais do que um operador
faria. Isso explica as filas, mas não o custo de cada consulta, que a tabela isolada mostra.

## Decisão
A decisão tem duas partes. A segunda depende de uma medição cujo critério fica fixado aqui, antes de se ver o
resultado.

**Parte 1: cada consulta do *dashboard* com custo limitado, e um *bulkhead* no *pool*.**
1. **Último registo de cada *host* por *lateral*** (`AverageLatestCPU`): para cada *host*, o registo mais
   recente pelo índice, em vez de ordenar a tabela toda. É o mesmo resultado (só entram os *hosts* com
   estatísticas) e custa uma pesquisa no índice por *host*.
2. **Nomes de aplicação por *loose index scan*** (CTE recursiva sobre `idx_error_logs_app_name`): uma pesquisa no
   índice por nome distinto, em vez de ler todas as linhas.
3. **Contagem de erros com teto** (`/errors`): conta-se no máximo até 10.001. Acima de 10.000, a página mostra
   "10000+" e pagina até à página 500. O custo fica limitado a 10.001 entradas de índice, com ou sem filtros.
4. **Contadores de erros por hora** (`error_counts_hourly`: hora em UTC, *host*, nível, contagem), mantidos por
   *triggers* de instrução no `error_logs` (inserção, atualização e remoção, com tabelas de transição), na mesma
   transação que a escrita. Os erros de hoje passam a ser a soma de, no máximo, 24 × *hosts* × níveis linhas.
   A migração preenche os contadores a partir dos dados existentes. A retenção limpa as horas expiradas.
5. **Índice de cobertura** para as métricas: `idx_machine_stats_host_collected` passa a incluir (`INCLUDE`) as
   cinco colunas que o *dashboard* agrega. As métricas de um *host* e o último registo de cada *host* leem só o
   índice, ordenado por *host* e tempo, sem uma leitura aleatória por linha. Substitui o índice atual (com a
   mesma chave), por isso não acrescenta um índice à escrita.
6. ***Bulkhead* do *dashboard*:** as rotas autenticadas do *browser* passam a ter um número máximo de pedidos em
   curso (`DASHBOARD_MAX_INFLIGHT`, por omissão 20 % do *pool*) e um prazo por pedido para o trabalho na base de
   dados (`DASHBOARD_QUERY_TIMEOUT`, por omissão 10 s, abaixo do `WriteTimeout` de 30 s). Um pedido que não
   consiga vaga em 2 s recebe 503 com `Retry-After`. Com o prazo, o PostgreSQL cancela a consulta (o `lib/pq`
   envia o cancelamento quando o contexto expira), em vez de a deixar a correr depois de o *browser* desistir.
   Somados, ingestão (60 %) e *dashboard* (20 %) deixam 20 % do *pool* para os *jobs* e as sessões.

**Parte 2: a retenção.** Com a Parte 1 feita, repete-se a mesma medição, sobre os mesmos dados. **Critério,
fixado antes da medição:** particionar por dia com `DROP PARTITION` se, na fase com retenção, se verificar
qualquer uma das três condições:
* o p95 da ingestão sobe mais de 20 % face à fase sem retenção;
* uma execução da retenção passa de 15 s (metade do *timeout*);
* os registos expirados continuam a crescer.

Se nenhuma se verificar, a retenção por `DELETE` em lotes fica, com a medição e um gatilho. Em qualquer dos
casos, a retenção passa a estar ativa por omissão (estatísticas e logs 30 dias; o plano, D9), com um intervalo e
um lote que acompanhem 1.000 *hosts*. A secção Resultado regista o que se mediu e o que se decidiu.

## Fundamentação teórica
* **Performance → *Increase Resource Efficiency*** (melhorar o algoritmo da consulta): *lateral* e *loose index
  scan* passam o custo de "proporcional à tabela" a "proporcional ao que se mostra" (1.000 *hosts*, uma dúzia de
  nomes).
* **Performance → *Bound Execution Times*:** a contagem com teto e o prazo por pedido limitam o pior caso de
  cada consulta, incluindo as que não se conseguem tornar rápidas (pesquisa por texto, ver Consequências).
* **Performance → *Maintain Multiple Copies of Computations*:** os contadores por hora são uma cópia agregada
  de `error_logs`, mantida na mesma transação, por isso nunca divergem.
* **Performance → *Reduce Overhead*:** o índice de cobertura elimina uma leitura do *heap* por linha.
* **Performance → *Limit/Schedule Resources* e Availability → *bulkhead*:** o *pool* passa a ter três
  compartimentos (ingestão, *dashboard*, resto). Uma consulta lenta deixa de poder parar a ingestão e os *jobs*,
  como o ADR-0006 já garantia no sentido inverso.
* **Modifiability → *Encapsulate*:** os contadores e o índice vivem atrás do repositório; nenhum *handler* nem
  serviço sabe que existem.
* **Análise tardia por medição** (slide 04): a estimativa do plano apontava para o volume e para a retenção; a
  medição mostrou que o estrangulamento era a forma das consultas, e que o *dashboard* parava a ingestão.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Particionar já, como o plano previa | Nenhuma das quatro consultas lentas tem um filtro temporal: o planeador leria todas as partições, e as consultas continuariam iguais. O particionamento resolve a retenção, não estas consultas. Fica para a Parte 2, se a medição o pedir |
| TimescaleDB (*hypertables* e *continuous aggregates*) | Resolveria os agregados, mas troca a imagem `postgres:16` por uma extensão e muda a operação, para um problema que se resolve com SQL e um índice. Continua em E2, com o gatilho |
| *Cache* em memória do resumo no central | Com N instâncias (ADR-0007), cada uma teria a sua cópia e o primeiro pedido depois de expirar continuaria a custar 55 s. Os contadores dão o valor exato com custo constante |
| Contadores mantidos no código da ingestão, em vez de *triggers* | O `seed-demo`, os testes e qualquer escrita futura teriam de se lembrar de os atualizar; um *trigger* vale para todas as escritas e não pode ser esquecido |
| Contagem exata no `/errors`, com estimativa do planeador (`reltuples`) | Rápido, mas falso com filtros, que é o caso comum. O teto é exato até 10.000, que é o que um operador lê |
| Baixar o `statement_timeout` de 30 s que o central já põe em todas as ligações (`internal/database/postgres.go`) | Os 30 s já existiam e não impediram nada: uma consulta de 55 s falha aos 30 s, mas prende a ligação esse tempo todo. Baixá-lo o suficiente para proteger o *pool* cortaria também a retenção e as escritas em lote. O prazo do *bulkhead* aplica-se só às rotas do *browser* |
| Mais ligações no *pool* | O PostgreSQL é o estrangulamento (ADR-0007, SC3). Mais ligações dariam mais consultas de 55 s em paralelo no mesmo CPU |

## Consequências
* **Positivas:**
  * O custo das consultas do *dashboard* deixa de crescer com os dias guardados: depende do número de *hosts*,
    de nomes de aplicação e do teto da contagem.
  * Uma consulta lenta já não consegue parar a ingestão nem os *jobs*.
  * A Parte 2 decide o particionamento com um número, não por antecipação.
* **Negativas / *trade-offs*:**
  * **Escrita mais cara:** cada lote de erros faz também um *upsert* nos contadores (uma linha por hora, *host*
    e nível do lote), e o índice das estatísticas fica maior (as cinco colunas). Medido na Parte 2, contra SC1.
  * **Migração mais lenta numa base grande:** recriar o índice e preencher os contadores lê as tabelas inteiras.
    Medida sobre os 143 GB, com o PostgreSQL limitado a 2 vCPU / 4 GB: **4 min 12 s** (preencher os contadores
    2 min 47 s; recriar o índice 1 min 25 s), com o central parado (o serviço `migrate` corre antes do arranque).
    O índice novo ocupa 6,5 GB e os contadores 332 MB (3,0 M linhas). A primeira tentativa **falhou**: a
    migração herdava o `statement_timeout` de 30 s das ligações e o `cmd/migrate` tinha um prazo fixo de 5 min. A
    migração passa a correr com `SET LOCAL statement_timeout = 0`, limitada pelo prazo do `cmd/migrate`, que
    passa a ser configurável (`MIGRATE_TIMEOUT`, por omissão 30 min). A transação falhada foi revertida por
    inteiro (o `Migrate` corre numa só transação), e o esquema ficou na versão 7.
  * **Contagem com teto:** acima de 10.000 erros, a página deixa de dizer o total exato.
  * **Pesquisa por texto** (`ILIKE`, sem índice) **continua lenta** quando o texto é raro, porque lê a tabela à
    procura de 20 resultados. Fica limitada pelo prazo do *bulkhead*: falha ao fim de 10 s, sem afetar mais
    nada. **Gatilho:** se a pesquisa for usada a sério, um índice `pg_trgm` ou uma janela temporal por omissão.
  * **Fora deste ADR:**
    * O *healthcheck* do Compose usa `/health`, igual a `/health/ready` (ADR-0010). Sob saturação, o central
      aparece `unhealthy`, e um orquestrador que reiniciasse contentores nesse estado mataria a instância
      quando ela mais trabalha. Num orquestrador, o *liveness* deve ser `/health/live`.
    * `telemetry_receipts` (40 GB em 30 dias) nunca é limpa (ADR-0003: os recibos sobrevivem aos dados para
      que um reenvio tardio não crie um duplicado). **Gatilho:** quando o seu tamanho passar o das tabelas de
      dados, limitar os recibos à idade máxima de um registo no *buffer* do remote.

## Verificação
* **SC4:** a mesma medição (`loadtest/correr.sh <iter> dashboard-30d`), sobre o mesmo volume de dados, depois da
  Parte 1. Passa se o p95 de **cada** uma das 7 consultas for < 1 s nas duas fases e se a ingestão cumprir SC1
  (p95 < 300 ms, nenhum lote perdido) na fase sem retenção. A fase com retenção decide a Parte 2 pelo critério
  acima.
* As mesmas consultas, isoladas, com `EXPLAIN (ANALYZE, BUFFERS)`, antes e depois.
* **Testes de integração:**
  * os contadores coincidem com `COUNT(*)` depois de inserir, deduplicar, atualizar e apagar erros;
  * o resumo dá o mesmo resultado que a consulta antiga;
  * os nomes de aplicação são os distintos;
  * a contagem pára no teto;
  * a retenção limpa as horas expiradas;
  * a migração preenche os contadores.
* **Testes unitários:** o *bulkhead* limita os pedidos em curso, responde 503 sem vaga, e aplica o prazo; a
  configuração fora dos limites é recusada; a página mostra "10000+" acima do teto.

**Resultado (21/11):** SC4 cumpre-se (`docs/metrics/iter-6/sc4-depois/`, tabela `carga-sc4.tex` com o antes e o
depois). É a mesma medição, sobre um histórico gerado de novo com o mesmo volume (89,3 M estatísticas, 238,8 M
erros, 143 GB).

| Medida | Antes, sem ret. | Antes, com ret. | Depois, sem ret. | Depois, com ret. | Alvo |
|---|---|---|---|---|---|
| p95 da consulta mais lenta do *dashboard* | 74,3 s | 73,6 s | **287 ms** (métricas de 1 mês) | **103 ms** (resumo) | < 1 s |
| p95 das outras seis | 28,9–71,0 s | 33,2–72,6 s | 16–176 ms | 16–100 ms | < 1 s |
| p95 da ingestão (agente) | 1.594 ms | 2.182 ms | **7,4 ms** | **4,9 ms** | < 300 ms |
| Pedidos rejeitados por sobrecarga | 58 % | 59 % | 0 | 0 | — |
| Registos confirmados em 10 min | 11.008 | 10.489 | 73.229 | 73.226 | todos (≈ 73.000) |
| Esperas por uma ligação do *pool* | 9.057 | 9.874 | 0 | 0 | — |
| Retenção: duração média / p95 | — | 7,4 s / 27 s | — | **0,33 s / 0,48 s** | — |
| Registos expirados por hora | +441 mil | −722 mil | +437 mil | −734 mil | ≤ 0 |
| CPU do PostgreSQL, média | 67 % | 66 % | 14 % | 10 % | — |
| Lotes perdidos / duplicados | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Os números de cada consulta isolada estão em `iter-6/sc4-antes/explain.txt` (antes) e em
`iter-6/sc4-depois/explain-consultas.sql` (depois): 55 s → 19 ms, 17 s → 0,6 ms, 13 s → 2 ms, 5,3 s → 265 ms (a
frio), 0,97 s → 121 ms (a frio). A ingestão sobre 30 dias de dados fica ao nível da medição nominal com a base
vazia (SC1). A fase com retenção dá valores ligeiramente melhores do que a fase sem retenção, porque corre
depois dela, já com a *cache* quente; a diferença é da ordem do ruído, não um efeito da retenção.

**Parte 2, decidida pelo critério fixado acima: não se particiona.** Nenhuma das três condições se verifica:
* o p95 da ingestão não sobe (7,4 → 4,9 ms);
* a execução mais longa da retenção fica em 0,48 s, contra um limite de 15 s;
* os expirados descem 734 mil por hora.

Antes, a retenção demorava até 27 s, não pelo seu próprio custo, mas porque esperava pelas ligações que o
*dashboard* ocupava. A retenção por `DELETE` em lotes fica, e passa a estar **ativa por omissão** com os valores
medidos: estatísticas e logs 30 dias, incidentes resolvidos 180, emails enviados 30, auditoria 365; a cada
**1 min**, até **10.000** linhas por categoria. Com 1.000 *hosts* isto remove 2,6 vezes o que entra, por isso o
dia de dados já expirados que o histórico trazia (11 M registos) leva cerca de 15 h a desaparecer.

**Gatilho para particionar** (com as métricas do ADR-0004, como as *fitness functions* do plano, §8):
* `monitor_job_duration_seconds{job="retention"}` com p95 acima de 15 s;
* ou o p95 da ingestão a subir mais de 20 % nos minutos em que a retenção corre;
* ou os registos com mais de 30 dias a crescer de um dia para o outro.

O particionamento diário com `DROP PARTITION`, tal como o plano o descreve (D9), continua a ser o passo
seguinte. A medição desfez a ideia de que o volume, por si só, o exigia a 1.000 *hosts*.

## Histórico
* 2026-11-21: secção Resultado e decisão da Parte 2 (não particionar; retenção ativa por omissão), depois da
  medição `iter-6/sc4-depois`. Corrigida a alternativa do `statement_timeout`: o central já tinha um global de
  30 s, e o que se rejeita é baixá-lo.
