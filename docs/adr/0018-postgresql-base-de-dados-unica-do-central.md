# ADR-0018: PostgreSQL como base de dados única do central, para a telemetria e para o resto

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Scalability, Availability (integridade dos dados), Modifiability
* **Cenários relacionados:** SC1–SC4, AV1; lacunas S2, S4, S7
* **Decisão do plano:** nenhuma (anterior ao plano). É registada agora porque os ADR-0005, 0006, 0007 e 0017 a
  pressupõem sem a justificar (ADR-0001: os ADR retroativos preservam o porquê das decisões que já existem).

## Contexto
O central guarda dois tipos de dados com perfis opostos:
* **Telemetria** (`machine_stats`, `error_logs`): séries temporais que só crescem, ≈ 10,5 M registos por dia
  com 1.000 *hosts*, consultadas por *host* e por intervalo de tempo e apagadas por idade;
* **Dados de domínio e de operação**: utilizadores, sessões, *hosts* e chaves, regras e incidentes de alerta,
  *outbox* de emails, auditoria, limites de *login*, estado do *buffer* de cada *host*. São relacionais, pequenos
  e muito alterados, e precisam de integridade referencial (apagar um *host* apaga a sua telemetria).

A propriedade de que a disponibilidade depende **atravessa os dois**: cada registo de telemetria é gravado na
**mesma transação** que o seu recibo de deduplicação (`telemetry_receipts`), e é isso que dá a entrega
*at-least-once* sem duplicados (AV1: 0 perdas, 0 duplicados em 1 h com o central em baixo, ADR-0012). Os
contadores de erros por hora do ADR-0017 seguem a mesma regra, e a avaliação de alertas lê a telemetria
recente ao lado das regras.

Restrições: uma equipa de 2 pessoas; *deploy* em Docker Compose com imagens oficiais; nenhum serviço gerido.

A escolha já estava no código quando o trabalho começou (iteração 0). O que este ADR acrescenta é a
justificação e a evidência que as medições entretanto deram.

## Decisão
Uma **única base de dados PostgreSQL 16**, a imagem oficial `postgres:16`, para todos os dados do central,
sem extensões. O esquema evolui por migrações numeradas, cada uma numa transação (`internal/database/migrate.go`).

O desenho usa capacidades do PostgreSQL que outras bases de dados não têm, ou têm de outra forma, e que
várias decisões posteriores pressupõem:

| Capacidade | Onde | Decisão |
|---|---|---|
| Transações ACID entre tabelas | registo + recibo; contadores por *trigger* | AV1; ADR-0017 |
| `INSERT … SELECT FROM unnest($n::array)` e `ON CONFLICT … RETURNING` | escritas em lote, recibos | ADR-0005 |
| `FOR UPDATE SKIP LOCKED` | *outbox*, *probes* devidas, retenção | ADR-0007, 0013 |
| *Advisory locks* | liderança dos *jobs*, migrações, retenção | ADR-0007 |
| Índices compostos, parciais e de cobertura (`INCLUDE`) | consultas por *host* e tempo | ADR-0013, 0017 |
| `LATERAL`, CTE recursivas, `date_bin` | *dashboard*, alertas | ADR-0008, 0017 |
| *Triggers* de instrução com tabelas de transição | contadores de erros por hora | ADR-0017 |
| `JSONB` | metadados dos erros, descartes do *buffer* | ADR-0010 |

## Fundamentação teórica
* **Padrão Shared-Data** (slide 04): o central partilha um repositório de dados entre a ingestão, o
  *dashboard* e os *jobs*. Os seus *trade-offs* são conhecidos e estão tratados: um ponto único de falha
  (ADR-0007, E4) e um estrangulamento, controlado pelos compartimentos do *pool* (ADR-0006 e 0017).
* **Estilo e dados** (slide 08, *"where should data live"*): o central é um monólito replicado sobre uma BD
  partilhada. Pôr a telemetria noutra base de dados criaria uma fronteira transacional entre o registo e o
  recibo. O slide 08 diz que uma transação a atravessar uma fronteira indica uma granularidade errada, e que as
  transações distribuídas são um dos desafios próprios dos sistemas distribuídos.
* **Availability → *Transactions*** (slide 03): a atomicidade registo + recibo é a tática que dá AV1.
* **Modifiability → *Defer Binding* / *Encapsulate*:** só os repositórios conhecem o SQL (as regras de camadas do
  `depguard`). É isso que permite que um passo como o E2 (TimescaleDB) não toque nos serviços.
* **Decisão guiada pela medição** (slides 04 e 06): as alternativas mais especializadas ficam para quando um
  gatilho medido o pedir (YAGNI).

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Uma base de dados de séries temporais (InfluxDB, Prometheus/VictoriaMetrics) para a telemetria, e outra relacional para o resto | Duas bases de dados: o registo e o recibo deixariam de estar na mesma transação, e a deduplicação passaria a precisar de idempotência entre sistemas ou de uma *saga* (slide 08). Duas coisas para operar, para fazer *backup* e para testar, com 2 pessoas. A 1.000 *hosts*, o PostgreSQL cumpre SC1, SC2 e SC4 (abaixo) |
| ClickHouse ou outra base de dados colunar | Excelente para agregar; mas sem transações entre tabelas nem `UPDATE`s baratos, que os incidentes, a *outbox* e as sessões fazem a toda a hora. Seria sempre uma segunda base de dados |
| TimescaleDB já (*hypertables*, *continuous aggregates*, compressão) | É PostgreSQL com uma extensão, por isso mantém tudo o que está acima. Mas troca a imagem oficial por outra, e o ADR-0017 mostrou que, a 1.000 *hosts* e 30 dias, o problema era a forma das consultas e não o volume. Fica como **E2**, o passo natural seguinte |
| MySQL / MariaDB | Daria para os dados relacionais, mas o desenho usa capacidades que não existem ou são diferentes: `RETURNING`, *arrays* com `unnest` nas escritas em lote, índices parciais e `INCLUDE`, *triggers* de instrução com tabelas de transição, `date_bin` |
| MongoDB ou outra base de documentos | O domínio é relacional (*hosts* → regras → incidentes → *outbox*), com integridade referencial e transações curtas. A telemetria é tabular |
| SQLite no central | Um só escritor por ficheiro: incompatível com várias instâncias (ADR-0007) e com centenas de escritas concorrentes. É a escolha certa no remote, com um só processo por *host* |

## Consequências
* **Positivas:**
  * Uma só tecnologia para operar, fazer *backup*, testar e migrar. Os testes de integração correm contra um
    PostgreSQL real num esquema isolado.
  * As garantias de integridade são locais: registo, recibo e contadores na mesma transação, sem coordenação
    entre sistemas.
  * **Evidência medida:**
    * SC1: p95 da ingestão de 6,2 ms no agente com 1.000 *hosts* (iter-3, `nominal.json`);
    * SC2: o *backlog* de 1 h é absorvido sem perdas nem duplicados e com o *dashboard* em p95 de 262 ms
      (iter-4);
    * SC4: 31 dias de dados (143 GB) com o *dashboard* em p95 ≤ 287 ms e a ingestão a 7,4 ms (ADR-0017).
* **Negativas / *trade-offs*:**
  * **É o estrangulamento das escritas** (SC3, ADR-0007): com 2 e 3 instâncias do central, o débito ficou em
    1,01× e 1,03×, porque todas escrevem no mesmo PostgreSQL. **Gatilho E9** (plano §8): *group commit* e
    depois particionar por *host* em vários nós (Citus).
  * **É um ponto único de falha.** O *store-and-forward* do remote cobre a indisponibilidade (AV1), mas não a
    perda do disco. **Gatilho E4:** réplicas e HA (Patroni ou um serviço gerido) quando houver um requisito de
    RTO.
  * **Os agregados de longo prazo são caros sem extensões:** o ADR-0017 resolveu-os com índices e contadores
    próprios. **Gatilho E2** (TimescaleDB): *dashboard* com p95 > 1 s em 30 dias, ou mais de 500 GB.
  * **As migrações sobre tabelas grandes demoram** (ADR-0017: 4 min 12 s em 143 GB) e correm com o central
    parado.

## Verificação
Não há uma medição nova: a decisão é verificada pelos cenários que já se mediram sobre ela (SC1, SC2, SC4 e
AV1 cumpridos; SC3 com o limite identificado e o gatilho E9). Os gatilhos E2, E4 e E9 usam as métricas do
ADR-0004 (latência e débito da ingestão, ligações do *pool*, duração dos *jobs*, tamanho das tabelas), por
isso a revisão desta decisão faz-se com os mesmos números.

## Histórico
