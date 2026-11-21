# ADR-0011: O remote retoma a entrega sem reinício

* **Estado:** Aceite
* **Data:** 2026-11-20
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability
* **Cenários relacionados:** AV3; MN1 (`delivery_paused`, ADR-0010); lacuna A1
* **Decisão do plano:** D16 (`../PLANO_MELHORIAS.md` §7.4)

## Contexto
O remote pausa a entrega quando o central responde com um código que não se resolve a tentar outra vez:
`UNAUTHENTICATED` (chave revogada ou regenerada), `PERMISSION_DENIED`, `INVALID_ARGUMENT` sem
`RecordRejection` (contrato violado) e códigos inesperados (ADR-0003). A pausa evita gastar a fila e
pedidos inúteis, mas hoje é **definitiva**: o ciclo de espera devolve `false` e os dois *workers* de entrega
terminam (`internal/sender/retry.go`, `wait`). Só um reinício do agente a desfaz (A1). Casos reais:

* o operador regenera a chave no central e atualiza o `.env` do host: os dados ficam parados até alguém
  reiniciar o agente, embora a chave já esteja certa;
* uma falha transitória do lado do central devolve um destes códigos (por exemplo, um balanceador mal
  configurado durante uma atualização): o agente fica parado para sempre por um erro de minutos;
* com o ADR-0010, `delivery_paused` nunca chegaria ao central, porque um agente em pausa não envia nada.

AV3 pede: 4xx transitório ou chave corrigida → entrega retomada em ≤ 5 min, sem reiniciar o remote.

## Decisão
1. **A pausa deixa de terminar os *workers*.** Em pausa, o agente faz **uma *probe* a cada 5 min**: um
   pedido com **um só registo** (o mais recente da categoria que acordar primeiro). A *probe* é partilhada
   pelas duas categorias, porque ambas usam a mesma chave: quem a reserva marca já a próxima para daqui a
   5 min, e a outra categoria dorme até lá.
2. **Retoma** quando o central prova que a chave e o contrato estão bons: aceitou o registo, ou rejeitou-o
   com `RecordRejection` (só o faz depois de autenticar e de validar o lote). A retoma acorda as duas
   categorias e o ciclo continua com lotes completos. Qualquer outro resultado mantém a pausa até à próxima
   *probe*. Retoma e pausa ficam no log do agente.
3. **`SIGHUP` recarrega a chave** (`HOST_API_KEY`) do `.env`, troca-a no cliente gRPC e antecipa a
   *probe* para já. Como no arranque, uma chave definida no ambiente do processo tem precedência sobre o
   `.env`. Os outros valores (endereço, intervalos, caminhos) continuam a exigir reinício. Antes, `SIGHUP`
   terminava o agente (comportamento por omissão do sinal).
4. O relógio do *sender* é injetável: o intervalo das *probes* testa-se sem esperar 5 minutos.

## Fundamentação teórica
* **Availability → Recover: *Retry*** — mas com uma cadência fixa e baixa, e uma carga mínima (um
  registo), porque a causa provável não se resolve sozinha em segundos.
* **Availability → Recover: *Escalating Restart*** no sentido brando: em vez de reiniciar o processo, reinicia-se
  só a entrega, e só depois de uma prova (*probe*) de que a causa desapareceu.
* **Modifiability → *Defer Binding*** (vinculação em tempo de execução): a credencial muda com o agente a
  correr, por sinal.
* **Monitorability:** a *probe* de estatísticas leva o estado do *buffer* com `delivery_paused = true`
  (ADR-0010): o central passa a saber que o host está em pausa.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| *Retry* normal (com *backoff*) para `UNAUTHENTICATED`/`PERMISSION_DENIED` | Lotes completos de 100 a cada poucos segundos, recusados: tráfego e carga de autenticação inúteis no central, multiplicados por 1.000 hosts |
| Manter a pausa até reiniciar (atual) | Falha AV3; um erro de minutos para o agente para sempre |
| Recarregar o `.env` periodicamente (sem sinal) | Leituras do disco sem motivo; o operador não sabe quando a chave nova entra em vigor. O sinal é explícito e a *probe* a cada 5 min cobre quem não o envia |
| Recarregar toda a configuração no `SIGHUP` | Endereço e intervalos mudam *workers* e ligações já criados: muito mais estado a reconstruir com o agente a correr, para casos que o reinício resolve bem |
| *Probe* com um pedido vazio | O contrato rejeita lotes vazios com `INVALID_ARGUMENT` antes de distinguir os outros casos; um registo real é a prova mais simples e não se perde (fica pendente se falhar) |

## Consequências
* **Positivas:** uma chave corrigida volta a entregar em ≤ 5 min sem intervenção, ou de imediato com
  `SIGHUP`; uma falha transitória não para o agente para sempre; o central vê a pausa.
* **Negativas / *trade-offs*:**
  * Um host com a chave revogada faz 12 pedidos por hora, de um registo cada. A 1.000 hosts todos
    revogados, 3,3 pedidos/s: desprezável face à ingestão normal.
  * A *probe* envia o registo mais recente, não o mais antigo; a ordem de entrega já é "mais recentes
    primeiro" (ADR-0003), por isso não muda nada.
  * `SIGHUP` só muda a chave. Mudar o endereço do central continua a exigir reinício (documentado).

## Verificação
* **AV3** — teste com relógio injetado no *sender* (`TestPausedDeliveryResumesWithinFiveMinutes`): o central
  responde `PERMISSION_DENIED` → pausa; antes dos 5 min nenhuma categoria faz pedidos; aos 5 min uma *probe*
  com 1 registo; o central passa a aceitar → a entrega retoma no mesmo ciclo e entrega tudo. Sem reiniciar
  e sem `sleep`.
* *Probe* falhada mantém a pausa e marca a próxima para daqui a 5 min; `RecordRejection` na *probe* retoma.
* *Workers* em pausa não terminam: o ciclo `run` retoma sozinho depois de uma *probe* com sucesso.
* `SIGHUP`: a chave relida do `.env` passa a ser enviada e a *probe* acontece de imediato; a chave do
  ambiente do processo tem precedência; um `.env` sem chave é recusado e mantém a anterior.

**Resultado (20/11):** AV3 passa (`docs/metrics/iter-6/av3.txt`): pausa por `PERMISSION_DENIED`, 0 pedidos
durante 4 min 59 s, *probe* de 1 registo aos 5 min (com `delivery_paused = true` no estado do *buffer*),
retoma no mesmo ciclo e entrega tudo. No processo real, `SIGHUP` relê a chave e o agente continua vivo. Para
caber nos limites de complexidade, `deliverBatch` foi partido em quatro funções; o lint do remote desceu de
24 para 21 *issues*.
