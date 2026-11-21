# ADR-0010: Estado do *buffer* reportado ao central; `/health/live` e `/health/ready`

* **Estado:** Aceite
* **Data:** 2026-11-20
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Monitorability (com Availability)
* **Cenários relacionados:** MN1, MN2; MO1 (medido aqui); lacunas A2, A3
* **Decisão do plano:** D17 (`../PLANO_MELHORIAS.md` §7.4)

## Contexto
**O central não vê o *buffer* dos hosts (A2, MN1).** O remote sabe quantos registos tem pendentes, quantos
pôs em quarentena, há quanto tempo espera o mais antigo, se a entrega está em pausa (chave revogada,
contrato violado) e, desde o ADR-0009, quantos descartou por nível. Nada disto sai do host: só se vê com
acesso à máquina e ao SQLite. Um registo em quarentena é um dado que nunca chega, sem ninguém saber.

**O `/health` só testa a base de dados (A3, MN2).** Desde o ADR-0007 cada *job* de fundo corre na instância
que o lidera. Se o *job* bloquear (uma chamada sem *timeout*, um *deadlock*), a liderança mantém-se (a sessão
PostgreSQL está viva), nenhuma outra instância o assume, e o `/health` continua a responder 200. Os alertas
deixam de ser avaliados ou as notificações de sair sem nenhum sinal. Os intervalos dos *jobs* hoje:

| *Job* | Intervalo |
|---|---|
| `notifications` | 5 s |
| `host_availability_alerts`, `metric_alerts` | 15 s |
| `host_health` | 30 s (`HostHealthInterval`) |
| `retention` | `CLEANUP_INTERVAL` (1 h por omissão) |
| `daily_summary` | 24 h |

**MO1 ainda não foi medido.** O ADR-0008 preparou o mecanismo; falta uma métrica nova real. A quarentena
reportada aqui é essa métrica (`buffer_quarantined`).

Forças: o contrato só aceita mudanças aditivas (ADR-0003, `buf breaking`); um dado de monitorização nunca pode
impedir a entrega da telemetria; o remote pausa a entrega perante `INVALID_ARGUMENT` sem detalhe (contrato
violado), por isso o central não pode rejeitar um lote por causa do estado do *buffer*.

## Decisão
1. **Contrato `monitor-api` v1.1.0, aditivo.** `IngestStatsRequest` ganha `optional BufferStatus buffer = 2`:
   `observed_at`, `pending`, `quarantined`, `oldest_pending_age_seconds`, `delivery_paused`, `size_bytes` e
   `dropped_by_kind` (mapa nível ou `machine_stat` → total acumulado, o `buffer_drops` do ADR-0009). Vai no
   pedido de estatísticas porque esse já é o sinal periódico do host (a cada 30 s): não há RPC nova nem
   autenticação a mais. Agentes antigos não o enviam e continuam a funcionar.
2. **Remote:** no início de cada ciclo de entrega de estatísticas tira uma fotografia do *buffer* (contagens
   pelos índices parciais; idade pelo `MIN(queued_at)` indexado; tamanho pelas páginas, ADR-0009) e envia-a em
   todos os lotes desse ciclo.
3. **Central:** valida o estado (valores não negativos, chaves conhecidas, `observed_at` não futuro). **Um
   estado inválido é ignorado**, com um aviso no log, e as estatísticas são aceites na mesma: o estado é
   acessório e não pode travar a telemetria. Guarda **o último por host** na tabela `host_buffer_status`
   (migração 5), na mesma transação das estatísticas, e só se `observed_at` for mais recente do que o guardado
   (lotes reenviados fora de ordem e várias instâncias, ADR-0007).
4. **Exposição:** a API JSON do *dashboard* (`/api/v1/dashboard/metrics`) inclui `buffer` do host
   selecionado. A apresentação no HTML fica para depois.
5. **Alerta `buffer_quarantined`** (prova de MO1): uma estratégia nova no pacote `alertmetric` (ADR-0008),
   com o número de registos em quarentena reportado nos últimos 5 minutos; migração 6 acrescenta o nome ao
   `CHECK`. Medem-se os ficheiros tocados e o tempo.
6. **`/health/live`**: 200 enquanto o processo responde, sem dependências. **`/health/ready`**: 200 só se a
   base de dados responde **e** cada *job* que esta instância lidera completou uma iteração (com sucesso ou
   erro) há menos de **2 × o seu intervalo**; senão 503, com os *jobs* atrasados no corpo. O registo de
   *heartbeats* recebe o relógio por injeção (testes sem `sleep`). `/health` passa a ser o mesmo que
   `/health/ready`. O *healthcheck* do Compose usa `/health/ready`.

## Fundamentação teórica
* **Availability → Detect Faults: *Heartbeat*** (cada iteração de um *job* é um batimento; o atraso é a falha),
  ***Monitor*** (o registo de *heartbeats* é o componente que vigia os *jobs*) e ***Self-Test*** (o
  `/health/ready` verifica as dependências da própria instância).
* ***Inform Actors***: a quarentena e os descartes do host chegam ao operador, e podem gerar um alerta.
* ***Maintain System Model***: o central passa a ter uma imagem do estado de cada agente.
* **Separação *liveness*/*readiness***: reiniciar resolve um processo bloqueado; retirar do tráfego resolve
  uma instância que ainda não pode servir. São respostas diferentes e precisam de sinais diferentes.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| RPC nova `ReportBufferStatus` | Mais uma chamada e uma autenticação por ciclo, para um dado que cabe no pedido que já existe a cada 30 s |
| Rejeitar o lote com estado inválido | O remote pausaria a entrega (contrato violado): um dado acessório travaria toda a telemetria |
| Guardar o histórico do estado | Ninguém o pede (MN1 quer o estado atual); os descartes já são acumulados, logo a diferença entre dois valores dá a taxa |
| Expor o estado em `/metrics` (Prometheus) com o host como *label* | 1.000 hosts × 6 séries: cardinalidade alta numa ferramenta de operação do central, não dos hosts |
| Considerar "parado" um *job* que falha | Um *job* que falha está vivo e já tem métrica de falhas (ADR-0004); o que não se via era o *job* bloqueado |
| *Ready* a verificar todos os *jobs*, liderados ou não | Uma instância seguidora não corre o *job*: não pode estar atrasada nele |

## Consequências
* **Positivas:** a quarentena de um host fica visível no central em ≤ 1 ciclo de estatísticas (30 s) e pode
  gerar um alerta; um *job* bloqueado põe a instância em 503 em ≤ 2 intervalos; MO1 fica medido.
* **Negativas / *trade-offs*:**
  * `delivery_paused` só chega ao central quando o remote volta a falar com ele: em pausa, hoje, não envia
    nada. Ganha utilidade com o D16 (ADR seguinte), que faz uma tentativa periódica em pausa.
  * **O nginx de código aberto não consulta o `/health/ready`:** só tem verificações passivas (falhas de
    ligação); as ativas são do nginx Plus. O *ready* serve o Compose (estado `unhealthy`, `depends_on`) e
    qualquer orquestrador com *readiness probe*. Gatilho para mudar de balanceador (HAProxy, que tem
    verificações ativas, ou um orquestrador): um *job* bloqueado em produção que o *ready* detetou e o
    balanceador não retirou.
  * Um ciclo legítimo mais longo do que 2 × o intervalo (por exemplo, sondas lentas, AV2) marca a instância
    como não pronta. É intencional: o ciclo atrasado é um problema real; o D7 trata as sondas.
  * Mais uma escrita (*upsert* de uma linha) por lote de estatísticas, na mesma transação.

## Verificação
* **MN1:** teste de integração no central (PostgreSQL): lote com `buffer.quarantined = 3` → a API do
  *dashboard* mostra 3; um estado mais antigo não substitui o mais recente; um estado inválido é ignorado e as
  estatísticas são gravadas. No remote: a fotografia conta a quarentena e segue em todos os lotes do ciclo.
* **MN2:** teste com relógio injetado: *job* liderado com intervalo de 15 s bloqueado → *ready* 200 aos 30 s e
  503 depois dos 30 s; um *job* não liderado nunca conta; *live* sempre 200.
* **Contrato:** `buf breaking` verde contra v1.0.0.
* **MO1:** registo de ficheiros Go, migrações e tempo da métrica `buffer_quarantined`; alvo ≤ 3 ficheiros Go +
  1 migração, ≤ 1 pessoa-dia.

**Resultado (20/11):** MN1 e MN2 passam (`docs/metrics/iter-6/mn1-mn2.txt`). MO1
(`docs/metrics/iter-6/mo1.md`): 3 ficheiros Go de produção (1 novo; `embed.go` e `migrate.go` registam a
migração) + 1 migração, 0 alterações no avaliador, no serviço, no *handler* e no formulário; antes eram 7 sítios
em 5 ficheiros e 3 camadas. Cumpre.
