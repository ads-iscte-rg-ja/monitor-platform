# ADR-0021: O SDK escreve diretamente no *buffer* SQLite do remote, cujo esquema pertence ao remote

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability, Modifiability
* **Cenários relacionados:** AV1, AV4, MO2
* **Decisão do plano:** nenhuma (anterior ao plano). O cap. 3 do relatório identifica-a como a dependência mais
  importante entre componentes que não aparece em nenhum `go.mod`.

## Contexto
As aplicações registam os seus erros através do SDK (`monitor-go-sdk`, `LogError`). Os erros têm de chegar ao
central com as garantias do ADR-0020: nada se perde com o central em baixo, e nada se duplica.

Forças em jogo:
* **a aplicação não pode ficar à espera nem falhar** por causa do Monitor: registar um erro tem de ser rápido e
  local;
* um erro registado tem de sobreviver a uma queda da aplicação logo a seguir (um *panic*, por exemplo);
* o SDK deve ser pequeno e não precisar do endereço nem da chave do central (o remote é que os tem);
* aplicação e remote correm no mesmo *host* e, normalmente, com o mesmo utilizador do sistema operativo.

## Decisão
1. **O SDK abre o mesmo ficheiro SQLite que o remote e escreve nele numa transação:** o erro em `error_logs` e a
   sua entrada em `delivery_status`. A partir daí, o registo segue o caminho do ADR-0020. O SDK não fala com o
   central nem com o remote.
2. **O esquema pertence ao remote.** O remote cria e valida o ficheiro (`database/schema.sql`) e recusa um ficheiro
   incompatível. O SDK nunca cria tabelas: verifica que as colunas de que depende existem e têm o tipo
   esperado, e falha com um erro claro se o *buffer* não foi preparado pelo remote.
3. **O acoplamento é verificado por testes**, porque nenhum compilador o vê. Os testes do SDK e do hello-world
   correm contra o `schema.sql` do remote, obtido no CI como repositório irmão (`sibling-repos`). Os níveis de
   log aceites são a mesma lista nos três repositórios, com testes de consistência (ADR-0015).

## Fundamentação teórica
* **Padrão Shared-Data** (slide 04): dois componentes comunicam por um repositório de dados partilhado, em vez
  de por chamadas. Desacopla-os no **tempo**: a aplicação escreve mesmo que o remote esteja parado, e o remote
  envia mais tarde.
* **Availability → *Transactions*:** o erro e a sua entrada na fila ficam gravados juntos, ou nenhum deles.
* **Conascência** (slide 08): SDK e remote têm **conascência de nome e de tipo** sobre o esquema (tabelas,
  colunas, tipos) e **de significado** sobre os níveis de log. É estática e, por isso, verificável. A decisão
  aceita-a e torna-a explícita, com o dono do esquema definido (o remote) e testes que falham quando os dois
  lados divergem, em vez de a deixar implícita como estava na iteração 0.
* **Performance → *Reduce Overhead*:** registar um erro é uma escrita local, sem rede nem serialização.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| O SDK envia ao remote por um *socket* local ou HTTP em `localhost` | Com o remote parado ou a reiniciar, o erro perde-se, ou o SDK precisa do seu próprio *buffer*, que é o que esta decisão evita. Acrescenta latência e um modo de falha ao caminho da aplicação |
| O SDK envia diretamente ao central | O SDK passaria a precisar do endereço, da chave e de toda a lógica de *retry*, quarentena e *backoff* do remote, repetida em cada linguagem. Com o central em baixo, cada aplicação acumularia o seu *backlog* |
| A aplicação escreve num ficheiro de log, e o remote lê-o (*tail*) | Desacopla o esquema, mas perde a atomicidade (um registo meio escrito), a validação à entrada e o estado por registo; o formato do ficheiro passa a ser o contrato, com o mesmo acoplamento e menos verificação |
| Uma API do SDK sobre um esquema versionado (migrações no SQLite) | Correta a prazo, mas o plano adiou as migrações do *buffer* (§9) enquanto não houver *hosts* em produção com dados por entregar. Fica com esse gatilho |

## Consequências
* **Positivas:**
  * Registar um erro não depende da rede, do central nem do remote estar a correr.
  * O SDK é pequeno e não guarda segredos: só o caminho do ficheiro.
  * AV1 cobre também os erros das aplicações (o E2E escreve-os pelo SDK, ADR-0012).
* **Negativas / *trade-offs*:**
  * **O acoplamento mais forte do sistema** atravessa dois repositórios: mudar o esquema do *buffer* obriga a
    mudar e libertar o SDK em conjunto. Mitigação: o dono do esquema é o remote, e os testes dos dois lados
    correm contra o mesmo `schema.sql`.
  * **Só funciona no mesmo *host*** e com acesso ao ficheiro (mesmo utilizador ou grupo). Uma aplicação num
    contentor precisa do ficheiro montado.
  * **SDK só em Go** (com CGO, por causa do SQLite). Um SDK noutra linguagem tem de respeitar o mesmo esquema; o
    `schema.sql` é o contrato (como o `.proto` do ADR-0003 é o do central).
  * **Concorrência no ficheiro:** a aplicação e o remote escrevem no mesmo SQLite. O WAL e o `busy_timeout` de
    5 s cobrem o caso normal; uma aplicação que registe milhares de erros por segundo compete com o remote pelo
    bloqueio de escrita (o limite do ADR-0009 protege o disco, não o débito).

## Verificação
* Testes do SDK contra o esquema real do remote (`TestConnectDBRejectsUnpreparedBuffers`,
  `TestLogErrorQueuesRecordForDelivery`, `TestLogErrorIsAtomic`), e o teste de integração do hello-world.
* Testes de consistência dos níveis de log entre os três repositórios (ADR-0015, MO2).
* E2E (ADR-0012): os erros entram pelo SDK e chegam ao central sem perdas nem duplicados (AV1).

## Histórico
