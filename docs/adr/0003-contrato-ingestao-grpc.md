# ADR-0003: Contrato de ingestão em gRPC, num repositório `monitor-api` versionado

* **Estado:** Aceite
* **Data:** 2026-11-19
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Modifiability (com Interoperability)
* **Cenários relacionados:** MO2, IO1; afeta SC1–SC3, SC5 (testes de carga) e AV1 (store-and-forward)
* **Substitui:** a alternativa "gRPC rejeitado" de D11 (`../PLANO_MELHORIAS.md` §7.3)

## Contexto
O remote envia a telemetria ao central por HTTP/JSON (`POST /api/v1/ingest/stats` e `/errors`). O contrato
entre os dois é **implícito**, e isso já causa acoplamento escondido (lacuna M2):

* o remote decide se põe um registo em quarentena comparando o **texto em inglês** da mensagem de erro do
  central com uma lista fixa de frases (`monitor-remote/internal/requests/failures.go`, `safeRecordReason`);
  mudar uma mensagem no central muda o comportamento do remote sem que nada falhe;
* as estruturas JSON estão definidas duas vezes, à mão, uma em cada repositório
  (`machineStatusPayload`/`errorLogPayload` no remote, `models.*Request` no central);
* a classificação das respostas (quarentena, dividir o lote, tentar mais tarde, pausar) depende de pares
  (código HTTP, campo `error`) que só estão documentados no código.

D11 tinha decidido tornar o contrato explícito com um campo `code` estável, uma especificação OpenAPI e
*fixtures* JSON testadas dos dois lados, e rejeitara o gRPC como "mudança de tecnologia sem ASR". Esta
decisão revê essa rejeição: o ASR existe (MO2, M2) e o gRPC resolve-o de forma mais forte do que a
especificação ao lado do código.

O desempenho **não** é argumento: a 1.000 hosts a ingestão são ~33 pedidos/s (plano §4.3), trivial para
HTTP/JSON.

## Decisão
1. **Contrato em Protocol Buffers**, serviço gRPC `monitor.ingest.v1.IngestService` com dois métodos
   unários, `IngestStats` e `IngestErrors`, com lotes de até 100 registos (como hoje).
2. **Repositório próprio `monitor-api`** (módulo Go `github.com/ads-iscte-rg-ja/monitor-api`), com o
   `.proto` e o código Go gerado, versionado por *tags* semânticas (`v1.x.y`). O central (servidor) e o
   remote (cliente) dependem dele pelo `go.mod`. A geração usa `buf`; o CI do repositório corre
   `buf lint`, `buf breaking` contra o `main` e verifica que o código gerado está atualizado.
3. **Erros com códigos estáveis**, nunca com texto:
   | Situação | Código gRPC | Detalhe | O remote… |
   |---|---|---|---|
   | Um registo inválido | `INVALID_ARGUMENT` | `RecordRejection{source_id, reason}` (`enum RejectionReason`) | põe esse registo em quarentena |
   | Lote inválido (vazio, >100, IDs repetidos) | `INVALID_ARGUMENT` | — | pausa (violação de contrato) |
   | Lote acima do tamanho máximo (1 MiB) | `RESOURCE_EXHAUSTED` | sem `RetryInfo` | divide o lote |
   | Sobrecarga (D6) | `RESOURCE_EXHAUSTED` | `google.rpc.RetryInfo` | tenta depois do atraso indicado |
   | Indisponível / falha interna | `UNAVAILABLE` / `INTERNAL` | `RetryInfo` opcional | tenta mais tarde |
   | Chave inválida | `UNAUTHENTICATED` | — | pausa até ser corrigida |
4. **Autenticação igual à atual**: a chave do host vai no metadado `x-api-key` e é validada por um
   *interceptor* antes de a mensagem ser processada; a identidade do host nunca vem do cliente.
5. **Os endpoints HTTP de ingestão são removidos.** Ainda não há hosts em produção, por isso não há
   período de transição. O dashboard e o resto da API continuam em HTTP.
6. **Transporte**: o central serve gRPC numa porta própria (`GRPC_PORT`), em texto simples atrás do
   mesmo proxy TLS que já serve o HTTP; o remote exige TLS fora de *loopback*, como hoje
   (`CENTRAL_GRPC_URL=https://…`).
7. A camada gRPC do central (`internal/grpcapi`) é uma camada de transporte, ao lado de `handlers`: usa
   `services`, nunca `repositories` nem `database` (nova regra `depguard`).

## Fundamentação teórica
* **Interoperability → Manage Interfaces / Orchestrate** (slide 03): o contrato passa a ser um artefacto
  próprio, com sintaxe **e semântica** (códigos de rejeição) explícitas; gerar clientes noutras linguagens
  a partir do `.proto` serve IO1.
* **Modifiability → Reduce Coupling / Encapsulate / Use an Intermediary**: o acoplamento semântico pelo
  texto das mensagens (M2) desaparece; as duas implementações dependem de uma interface versionada e não
  uma da outra. `buf breaking` torna uma alteração incompatível um erro de CI, que é a medida de MO2.
* **Restrict Dependencies + versionamento** (como o `@v1` do ADR-0002): central e remote escolhem a versão
  do contrato que usam.
* Padrão **Client-Server** mantido; muda o conector (de REST/JSON para RPC/HTTP2).

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| D11 original: HTTP/JSON + campo `code` + OpenAPI + *fixtures* | Resolve M2, mas a especificação fica **ao lado** do código: nada obriga as duas implementações a segui-la, só os testes de *fixtures*. Com protobuf o compilador obriga |
| `.proto` dentro do `monitor-central` | O remote passaria a depender do repositório e das versões do central; o contrato é do sistema, não de um componente |
| Cópia do `.proto` em cada repositório + teste de comparação | Duas cópias divergem; é exatamente o problema de M2 |
| Manter HTTP e gRPC ao mesmo tempo | Duplica autenticação, validação e o controlo de admissão (D6), sem hosts em produção que o justifiquem |
| gRPC com *streaming* para o *backlog* | Os lotes unários de 100 já cumprem SC2 nas estimativas; *streaming* complica o controlo de admissão e a deduplicação (YAGNI) |

## Consequências
* **Positivas:** contrato único e tipado; o remote deixa de depender do texto das mensagens; alterações
  incompatíveis detetadas no CI; clientes noutras linguagens gerados a partir do `.proto` (IO1).
* **Negativas / trade-offs:**
  * mais um repositório e um passo de geração de código; mitigado por o código gerado ficar versionado no
    `monitor-api`, e os consumidores não precisarem do `buf`;
  * um balanceador entre remote e central tem de suportar HTTP/2 (SC3, D8);
  * o controlo de admissão (D6) deixa de usar `429 + Retry-After` e passa a `RESOURCE_EXHAUSTED + RetryInfo`;
  * os testes de carga (D10) usam o cliente gRPC do k6 (`k6/net/grpc`);
  * depurar à mão exige `grpcurl` em vez de `curl`;
  * IO1 passa a referir o `.proto` em vez de OpenAPI.

## Verificação
* **MO2:** mudar o texto de uma mensagem de erro no central não altera o comportamento do remote (teste:
  o remote decide só pelo `RejectionReason`); uma alteração incompatível ao `.proto` faz falhar `buf breaking`.
* **AV1 / store-and-forward:** os testes do remote cobrem os quatro comportamentos (quarentena, dividir,
  tentar mais tarde, pausar) contra um servidor gRPC em memória (`bufconn`).
* **SE1:** chave inválida → `UNAUTHENTICATED` e nada persistido (teste no central).
