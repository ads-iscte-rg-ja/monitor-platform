# IO1: um agente noutra linguagem implementável só com o contrato publicado

**Cenário (relatório, cap. 4; (L,M)):** um agente noutra linguagem é implementável só com o contrato
publicado (`monitor-api`, ADR-0003).

**Evidência (21/11/2026):** o gerador de carga do D10 (`loadtest/k6/ingestao.js`) **é** esse agente. Está
escrito em **JavaScript**, corre no k6 e fala com o central só através do contrato:

* o único artefacto do sistema que usa é o `.proto`: `client.load(['/proto'], 'monitor/ingest/v1/ingest.proto')`,
  com o diretório `proto/` do `monitor-api` montado só de leitura (`loadtest/compose.yaml`). Não importa nenhum
  código Go do sistema, nem do central nem do remote;
* tudo o que precisa de saber sobre o comportamento está nos comentários do próprio contrato
  (`ingest.proto`, 153 linhas): a autenticação pelo metadado `x-api-key`; a entrega *at-least-once* com
  deduplicação por (*host*, tipo, `source_id`); o que fazer com cada código gRPC (`RESOURCE_EXHAUSTED` com e sem
  `RetryInfo`, os códigos definitivos) e o `RejectionReason` estável de cada registo rejeitado;
* a lógica de agente ocupa **101 linhas** de código (sem comentários nem linhas vazias), entre `iniciarHost` e o
  cenário contínuo: lotes de até 100, o mais recente primeiro, novas tentativas com o *backoff* e o atraso
  pedido pelo central, e paragem nas falhas definitivas.

**Resultado:** o agente em JavaScript entrega com as mesmas garantias que o remote em Go. Na medição
`iter-6/sc4-depois` (fase sem retenção), confirmou **73.229 registos, todos gravados, 0 duplicados e 0 lotes
perdidos**. Nas iterações 3 a 5 fez o mesmo em todos os cenários de carga, incluindo a recuperação de SC2
(441.000 registos, 0 perdidos, 0 duplicados). IO1 cumpre-se.

**Limites da evidência:**
* O contrato cobre o que passa na rede. A **durabilidade local** (guardar os registos com o central em baixo)
  é responsabilidade de cada agente (ADR-0020): o agente k6 guarda o *backlog* em memória, o que basta para
  medir, mas não para produção.
* O agente foi escrito pela mesma equipa que escreveu o contrato. Um agente escrito por terceiros seria uma
  prova mais forte; aqui, a evidência é que o código do agente só usa o `.proto` e os seus comentários.
* Uma falha encontrada pelo próprio agente mostra que o contrato tem de ser lido com atenção: no k6 2.x,
  `res.status` é o **nome** do código gRPC, e a comparação numérica nunca acertava; o agente passou a comparar
  `res.error.code` (iteração 3, medição corrigida). O contrato estava certo; a biblioteca de cliente é que o
  expunha de outra forma.
