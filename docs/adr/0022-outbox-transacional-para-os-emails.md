# ADR-0022: *Outbox* transacional para os emails dos alertas

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Availability
* **Cenários relacionados:** AV2 (o alerta tem de chegar a quem está de serviço); SC3 (várias instâncias)
* **Decisão do plano:** nenhuma (anterior ao plano; o ADR-0001 cita-a como decisão implícita).

## Contexto
Quando um alerta dispara, o central cria um incidente (`alert_events`) e envia um email por SMTP. O email é
o que avisa quem está de serviço: um incidente gravado sem email é um alerta que ninguém vê.

Forças em jogo:
* o servidor SMTP é externo e falha, ou está lento, de forma independente do central;
* gravar o incidente e enviar o email são duas operações em dois sistemas. Sem coordenação, há dois modos de
  falha: o incidente é gravado e o email nunca sai (o central cai entre as duas), ou o email sai e o incidente
  não fica gravado (a transação é anulada depois do envio);
* com várias instâncias do central (ADR-0007), o mesmo email não pode sair duas vezes;
* o resumo diário também é um email, e não pode sair duas vezes no mesmo dia.

## Decisão
1. **O email é gravado na mesma transação que o incidente**, numa tabela `email_outbox`, com uma chave de
   deduplicação única (`dedupe_key`, `ON CONFLICT DO NOTHING`). Se a transação for anulada, o email também é.
2. **Um *job* entrega a *outbox*:** reclama um email pendente com `FOR UPDATE SKIP LOCKED` e um prazo de 2 min
   (`locked_until`), envia-o e marca-o como enviado. Se a instância cair a meio, o prazo expira e outra
   instância volta a reclamá-lo.
3. **Uma falha do SMTP reagenda o email** com *backoff* exponencial (15 s a duplicar, até 1 h), sem limite de
   tentativas. O erro guardado é genérico ("SMTP delivery failed"), para não persistir dados do destinatário
   nem mensagens do servidor.
4. A marcação como enviado só vale para a tentativa que a pediu (`attempts = $2`), para que uma instância lenta
   não marque como enviado um email que outra já reclamou de novo.
5. Os emails enviados são apagados pela retenção (30 dias por omissão, ADR-0017). Os pendentes nunca o são.

## Fundamentação teórica
* **Padrão *Transactional Outbox*:** a escrita no sistema externo passa a ser uma escrita local, na mesma
  transação que o resto; um processo separado entrega-a depois. É a forma padrão de evitar uma transação
  distribuída entre a base de dados e um sistema externo (slide 08: transações distribuídas e a falácia 1).
* **Availability → *Retry*** com *backoff*, e ***Transactions***.
* **Availability → *Ignore Faulty Behavior*** no sentido inverso: um SMTP em baixo atrasa os emails, mas não
  bloqueia a avaliação de alertas nem a ingestão.
* **Entrega *at-least-once* com deduplicação**, como a telemetria (ADR-0020): a `dedupe_key` impede o
  duplicado no lado da criação; no lado do envio, o prazo pode, no pior caso, reenviar um email (ver
  Consequências).

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Enviar o email dentro da avaliação do alerta, de forma síncrona | Um SMTP lento atrasa a avaliação de todos os alertas; um SMTP em baixo perde o email ou obriga a anular o incidente |
| Enviar depois do `COMMIT`, numa *goroutine* | Se a instância cair entre o `COMMIT` e o envio, o email perde-se e ninguém o volta a tentar |
| Uma fila externa (RabbitMQ, SQS) | Volta a ser uma escrita em dois sistemas, que é o problema que a *outbox* resolve, e é mais um serviço para operar (ADR-0018) |
| Um número máximo de tentativas | Um SMTP em baixo durante horas faria desistir de alertas reais. Com o *backoff* até 1 h, tentar para sempre custa uma escrita por hora por email |

## Consequências
* **Positivas:**
  * Nenhum incidente fica sem o seu email, e nenhum email sai sem o seu incidente.
  * O SMTP pode estar em baixo durante horas sem efeito na avaliação de alertas nem na ingestão.
  * Funciona com várias instâncias sem coordenação adicional (`SKIP LOCKED`).
  * Os emails pendentes são observáveis (`monitor_email_outbox_pending`, ADR-0004).
* **Negativas / *trade-offs*:**
  * **Pode, raramente, sair um email em duplicado:** se o envio por SMTP for aceite e a instância cair antes de
    marcar o email como enviado, o prazo expira e outra instância reenvia-o. É o lado *at-least-once* da
    decisão: preferimos um email repetido a um alerta perdido.
  * **O email chega com atraso**, entre a avaliação e o próximo ciclo do *job*; com o SMTP em baixo, até 1 h
    depois de ele voltar.
  * Os emails pendentes de um SMTP em baixo acumulam-se na base de dados (mitigado: são poucos e pequenos, e
    a métrica `monitor_email_outbox_pending` mostra-os).

## Verificação
Teste de integração `TestAtomicOutboxRollbackConcurrencyAndRetry`: uma transação anulada não deixa email;
duas instâncias concorrentes não reclamam o mesmo email; uma falha reagenda com *backoff*.
`TestNotificationClaimsAndExpiredLeaseRecovery`: um email reclamado por uma instância que caiu é recuperado
depois do prazo. `TestRetentionIsBoundedPreservesPendingAndRetryReceipts`: a retenção nunca apaga um email
pendente.

## Histórico
