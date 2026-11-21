# ADR-0020: *Store-and-forward* em SQLite no remote, com entrega *at-least-once* e recibos de deduplicação no central

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability
* **Cenários relacionados:** AV1, AV3, AV4, SC2; MN1
* **Decisão do plano:** nenhuma (anterior ao plano). Os ADR-0003, 0009, 0010 e 0011 constroem sobre esta decisão
  sem a justificar (ADR-0001).

## Contexto
O objetivo G1 do sistema é não perder telemetria quando o central está em baixo ou inacessível. A aplicação
e a máquina continuam a gerar erros e estatísticas durante a falha, e é precisamente aí que mais importam:
uma avaria do central coincide muitas vezes com problemas na rede ou no próprio *host*.

Forças em jogo:
* o remote corre no *host* monitorizado, com os recursos dele, e não pode afetar as aplicações;
* a rede falha, e às vezes durante horas (falácia 1 do slide 08: *"the network is reliable"*);
* um registo entregue duas vezes não pode criar um duplicado nem disparar um alerta duas vezes;
* depois de uma falha, mil *hosts* reenviam ao mesmo tempo (SC2).

## Decisão
1. **Guardar primeiro, enviar depois.** Cada registo é gravado num ficheiro SQLite local, no *host*, na mesma
   transação que a sua entrada na fila de entrega (`delivery_status`). O ficheiro é privado (0600), com
   `journal_mode=WAL` e `synchronous=FULL`, para sobreviver a uma queda do processo ou da máquina.
2. **Enviar em lotes, o mais recente primeiro.** Os *workers* de envio leem lotes de até 100 registos e enviam-nos
   pelo contrato do ADR-0003. Um registo só sai da fila quando o central confirma.
3. **Repetir as falhas transitórias** com *backoff* exponencial e *jitter* (5 s a duplicar, até 5 min) e
   respeitando o atraso pedido pelo central (ADR-0006). Um registo que o central rejeita como inválido vai para
   **quarentena** e não bloqueia os outros (ADR-0003); a quarentena é visível no central (ADR-0010).
4. **Entrega *at-least-once* com deduplicação no central.** Cada registo leva um identificador de origem por
   *host* e tipo. O central grava o registo na **mesma transação** que um recibo
   (`telemetry_receipts(host_id, kind, source_id)`). Um reenvio encontra o recibo e não cria nada de novo
   (ADR-0005, ADR-0018).
5. Os registos entregues são apagados do *buffer* passados `SENT_RETENTION_DAYS` (7 por omissão). O tamanho
   total tem um limite, com descarte por severidade (ADR-0009).

## Fundamentação teórica
* **Availability → *Retry* e *State Resynchronization*** (slide 03): o *backlog* é reenviado quando o central
  volta, até à confirmação.
* **Availability → *Transactions*:** registo e entrada na fila numa transação local; registo e recibo numa
  transação no central. Nenhuma das duas atravessa a rede.
* **Availability → *Ignore Faulty Behavior*:** a quarentena isola o registo inválido.
* **Padrão *Store-and-Forward*** e **Shared-Data** (slide 04) do lado do *host*.
* **Falácias da computação distribuída** (slide 08): a decisão parte do princípio de que a rede falha e de que
  a latência não é zero, em vez de o ignorar.
* **Transações distribuídas evitadas** (slide 08): em vez de coordenar remote e central numa só transação (2PC),
  cada lado tem a sua, e a idempotência do recibo fecha a lacuna entre elas.
* ***Prioritize Events*** (desempenho): os registos mais recentes primeiro, porque são os que interessam para
  os alertas.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Enviar diretamente, sem *buffer* | Tudo o que é gerado com o central em baixo perde-se: falha G1 e AV1 por definição |
| *Buffer* em memória | Perde-se com o reinício do remote ou do *host*, que é frequente durante um incidente |
| Ficheiro de *log* com *append* (por exemplo, JSON Lines) | Simples, mas o estado por registo (enviado, em quarentena, tentativas), o descarte por severidade e o acesso concorrente da aplicação (ADR-0021) teriam de ser reinventados sobre um ficheiro. O SQLite dá isso com transações |
| *Broker* local (NATS, MQTT, RabbitMQ) no *host* | Mais um serviço a instalar, a configurar e a manter vivo em cada *host* monitorizado, consumindo os recursos que o Monitor devia proteger |
| *Exactly-once* com confirmação em duas fases | Exige coordenar dois sistemas por registo. O *at-least-once* com recibos idempotentes dá o mesmo resultado observável (0 duplicados) sem coordenação |
| Deduplicar pelo conteúdo (*hash* do registo) | Dois erros iguais e legítimos (o mesmo *timeout* duas vezes) seriam fundidos num só |

## Consequências
* **Positivas:**
  * **AV1 cumprido**, ponta a ponta: 1 h com o central em baixo, 0 registos perdidos e 0 duplicados (ADR-0012,
    3.603 s).
  * **SC2:** os 441.000 registos de 1 h de *backlog* de 1.000 *hosts* são entregues sem perdas nem duplicados
    (iter-3 a iter-5).
  * Um central lento não bloqueia a aplicação: ela escreve localmente e continua (ADR-0021).
* **Negativas / *trade-offs*:**
  * **Ocupa disco no *host*** durante uma falha longa. É o risco S9, tratado pelo limite do ADR-0009 (AV4:
    nunca passa o limite e só perde INFO/WARN, contados).
  * **O central guarda os recibos para sempre**, para que um reenvio tardio não crie um duplicado:
    `telemetry_receipts` ocupa 40 GB em 30 dias com 1.000 *hosts* (ADR-0017). **Gatilho:** quando passar o
    tamanho das tabelas de dados, limitar os recibos à idade máxima de um registo no *buffer*.
  * **O esquema do *buffer* não tem migrações:** um ficheiro incompatível é recusado no arranque, em vez de
    ser convertido (plano §9, adiado até haver *hosts* em produção com dados por entregar durante uma
    atualização).
  * **Dados mais antigos chegam por último**, por desenho: depois de uma falha longa, o *dashboard* fica
    completo do presente para o passado.

## Verificação
Já verificada pelos cenários que dependem dela: **AV1** (E2E de 1 h: 0 perdas, 0 duplicados), **SC2**
(recuperação com 1.000 *hosts*), **AV3** (retoma sem reinício, ADR-0011) e **AV4** (limite do *buffer*,
ADR-0009). Testes: atomicidade registo + fila no remote, recibos idempotentes no central
(`TestNumericIDsHostScopeAndIdempotency`, `TestRetentionIsBoundedPreservesPendingAndRetryReceipts`).

## Histórico
