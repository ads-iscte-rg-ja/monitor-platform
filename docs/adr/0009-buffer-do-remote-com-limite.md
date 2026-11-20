# ADR-0009: *Buffer* do remote com limite e descarte por severidade

* **Estado:** Aceite
* **Data:** 2026-11-20
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability (do host monitorizado), com Performance
* **Cenários relacionados:** AV4; AV1 (compatibilidade); lacuna S9
* **Decisão do plano:** D19 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
O remote guarda tudo num SQLite local (*store-and-forward*) até o central confirmar. A limpeza só apaga
registos **já entregues** (`internal/repository/cleanup.go`); pendentes e quarentena nunca saem. Não há
limite: com o central em baixo e uma aplicação em ciclo de erro, o *buffer* cresce até encher o disco, e o
monitor deita abaixo o host que devia proteger (S9).

Medido no esquema atual, com o *driver* do remote (`mattn/go-sqlite3`, páginas de 4 KiB):

| Medição | Valor |
|---|---|
| Espaço por log típico (mensagem de ~110 B, metadados de 40 B, tabela + fila + índices) | **358 B** |
| `auto_vacuum` no ficheiro criado pelo remote | `NONE` (0): o ficheiro nunca encolhe; as páginas libertadas vão para a *freelist* e são reutilizadas |
| Apagar 59 mil de 100 mil logs **intercalados** com ERROR | 5.085 de 8.739 páginas libertadas (58 %) |

Com 358 B/log, 512 MiB guardam ~1,5 milhões de logs. A rajada do modelo de carga (§4.4: 200 logs/s durante
2 min) ocupa 8,6 MB; a mesma rajada durante 1 h de central em baixo, 258 MB. Um ciclo de erro sem fim, ou
um central em baixo durante um fim de semana, passa qualquer valor fixo. A última linha mostra que se pode
medir o *buffer* pelas páginas em uso e que apagar só os INFO devolve espaço, mesmo com os ERROR misturados.

Forças: o host está primeiro (o monitor não o pode prejudicar); os ERROR são o que explica um incidente; AV1
(0 perdas com 1 h de central em baixo) continua a valer na carga normal; a aplicação nunca espera pelo monitor.

## Decisão
1. **Tamanho medido em páginas em uso:** `(page_count − freelist_count) × page_size`, duas *PRAGMAs* sem
   leitura de dados. Não o tamanho do ficheiro, que não encolhe; como as páginas livres são reutilizadas, o
   ficheiro fica limitado pelo máximo que o tamanho em uso atingiu.
2. **Dois limites**, em MiB: `BUFFER_MAX_MB` (suave, por omissão 512) e `BUFFER_HARD_MAX_MB` (rígido, por
   omissão o dobro do suave; tem de ser ≥ suave).
3. **Um *worker* próprio** (`BUFFER_CHECK_INTERVAL`, por omissão 10 s, entre 1 s e 5 min), separado da
   limpeza horária: a limpeza é retenção, o limite é proteção, e precisa de reagir em segundos.
4. **Política de descarte**, sempre dos mais antigos para os mais recentes, em lotes de 500 registos por
   transação (as escritas do SDK esperam no máximo uma transação curta):
   * acima do limite suave, até 90 % dele: (a) registos já **entregues** (não é perda, o central tem-nos);
     (b) logs pendentes **INFO**; (c) **WARN**; (d) **estatísticas** pendentes da máquina;
   * só se, depois disso, ainda estiver acima do limite **rígido**, até 90 % dele: (e) registos em
     **quarentena**; (f) **ERROR**; (g) **CRITICAL**; (h) **PANIC**. Nesse caso o remote grava no próprio
     *buffer* um log **CRITICAL** (`app = monitor-remote`) com o que descartou: chega ao central pelo caminho
     normal e dispara as regras `error_level` existentes.

   As estatísticas ficam na fase suave porque são amostras periódicas (a seguinte substitui a anterior); um
   ERROR é um evento único. A margem de 10 % (histerese) evita aparar o *buffer* em todos os ciclos.
5. **Descartes contados e persistidos:** tabela `buffer_drops(kind, dropped, last_dropped_at)`, atualizada
   **na mesma transação** que apaga (um descarte nunca fica por contar, nem é contado sem acontecer).
   `kind` é o nível do log ou `machine_stat`; os contadores só sobem. São o `dropped_by_level` que o D17 vai
   reportar ao central. Cada ciclo com descartes escreve uma linha no log do agente.
6. **Índice `error_logs(level, id)`**, para escolher os mais antigos de um nível sem percorrer a tabela.
7. **Sem migração:** a tabela e o índice são `CREATE … IF NOT EXISTS`, criados na abertura do *buffer*, como o
   resto do esquema; *buffers* existentes ganham-nos sem perder dados.

## Fundamentação teórica
* **Performance → *Bound Queue Sizes*** (gerir recursos): o *buffer* é uma fila e passa a ter um tamanho
  máximo; e **→ *Prioritize Events***: quando é preciso descartar, a severidade decide a ordem.
* **Availability → *Degradation***: perde-se o menos importante (INFO, WARN, amostras) para manter o
  essencial (ERROR+) e, acima de tudo, o host.
* **Monitorability / Availability → *Inform Actors***: cada perda é contada e persistida; a perda de ERROR+
  gera um evento CRITICAL que o operador recebe como alerta. A perda deixa de ser silenciosa.
* **Separação de responsabilidades**: a política vive no remote, dono do *buffer*; o SDK e as aplicações não mudam.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Bloquear o SDK com o *buffer* cheio (*backpressure*) | A aplicação monitorizada passaria a esperar pelo monitor: inaceitável num instrumento de observação |
| Descarte FIFO sem olhar à severidade | Numa tempestade de INFO perdiam-se precisamente os ERROR que explicam o incidente |
| Amostragem no SDK | Põe a decisão em cada aplicação e obriga a mudar todas as integrações; fica na evolução (E8) |
| Limite pelo tamanho do ficheiro, com `VACUUM` | Com `auto_vacuum=NONE` o ficheiro não encolhe; `VACUUM` reescreve a base inteira, precisa do dobro do espaço e bloqueia as escritas do SDK, justamente quando o disco está a acabar |
| Um *trigger* SQLite que apaga no `INSERT` | O SQLite não sabe o tamanho em bytes dentro de um *trigger* sem custo por escrita; poria a política no caminho quente da aplicação |
| Limite em número de registos | Os registos variam de ~300 B a ~110 KB (*stack trace* de 64 KiB + metadados de 32 KiB): um limite em número não protege o disco |

## Consequências
* **Positivas:** o disco do host fica limitado por um valor configurado; em rajadas, os ERROR+ sobrevivem; as
  perdas ficam contadas e prontas para o D17. AV1 mantém-se: o limite suave só atua acima de ~1,5 milhões de
  logs, e 1 h de central em baixo com a carga do §4.4 fica muito abaixo disso.
* **Negativas / *trade-offs*:**
  * Em situações extremas perdem-se INFO, WARN e amostras. É aceite, documentado e contado.
  * **O limite é aplicado periodicamente:** entre dois ciclos, o *buffer* pode passar o limite em, no
    máximo, débito × intervalo. Estimativa: a 1.000 logs/s (acima do que uma escrita com `synchronous=FULL`
    por log permite numa máquina comum) × 358 B × 10 s ≈ 3,6 MB, 0,7 % de 512 MiB. Mitigação: intervalo
    configurável.
  * O ficheiro WAL não conta no tamanho em uso; em operação normal fica no *checkpoint* automático do SQLite
    (1.000 páginas, ~4 MiB).
  * Um *buffer* que já cresceu antes desta versão não encolhe (não se faz `VACUUM`); deixa de crescer.
  * Um registo apagado enquanto está a ser enviado faz falhar a confirmação desse lote; o lote é reenviado
    no ciclo seguinte e o central deduplica pelo ID de origem, como em qualquer reenvio. Só acontece com o *buffer* acima do limite.

## Verificação
* **AV4** — teste de integração no remote (`TestBufferLimitAV4Burst`): *buffer* de 1 MiB, rajada de INFO +
  ERROR em vários ciclos com o central em baixo (nada é entregue). Depois de cada ciclo: tamanho ≤ limite;
  **0 ERROR perdidos**; INFO descartados = INFO gravados − INFO que restam, e o contador persistido igual a
  esse número (também depois de reabrir o ficheiro).
* Limite rígido: só ERROR+ acima do limite → descarte dos mais antigos, ERROR antes de CRITICAL antes de
  PANIC, e o evento CRITICAL fica no *buffer*.
* Ordem da fase suave: entregues → INFO → WARN → estatísticas; pendentes ERROR+ e quarentena intocados.
* Configuração: valores por omissão, intervalos válidos e `BUFFER_HARD_MAX_MB` < `BUFFER_MAX_MB` rejeitado.
