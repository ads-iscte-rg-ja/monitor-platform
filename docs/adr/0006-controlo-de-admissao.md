# ADR-0006: Controlo de admissão na ingestão, com ligações reservadas para o resto do central

* **Estado:** Aceite
* **Data:** 2026-11-19
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Scalability (com Availability)
* **Cenários relacionados:** SC2; AV1 (nada se perde); SC5; lacunas S4, S10
* **Decisão do plano:** D6 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
Na baseline de carga (iteração 3), a recuperação (SC2) entrega as 441.000 linhas do *backlog* em 1,4 min sem
perdas, mas o *dashboard* fica com p95 ≥ 10 s: a ingestão ocupa as 25 ligações do *pool* e o *dashboard* espera
por uma livre. Nada limita quantos pedidos de ingestão estão a ser servidos ao mesmo tempo (S4). O limite de
15 min de SC2 é folgado: há margem para trocar velocidade de absorção por estabilidade.

O plano previa também justiça por host (um *token bucket* por host, S10). A baseline refutou o risco que a
justificava: com 1 % dos hosts em rajada de 200 logs/s, os restantes tiveram atraso p95 de 6 ms (SC5).

## Decisão
1. **Limite de pedidos de ingestão em curso** (`INGEST_MAX_INFLIGHT`, por omissão 60 % de
   `POSTGRES_MAX_OPEN_CONNS`, ou seja 15 de 25). Cada pedido usa no máximo uma ligação de cada vez (autenticação,
   depois a transação), por isso a ingestão nunca ocupa mais de 15 ligações e ficam pelo menos 10 para o
   *dashboard*, as sessões e os *jobs*. O valor tem de ser menor do que o *pool*.
2. **Rejeitar sem esperar**: com o limite atingido, o pedido recebe logo `RESOURCE_EXHAUSTED` com `RetryInfo`
   aleatório entre 1 e 10 s (ADR-0003). O remote já respeita o `RetryInfo`: os registos ficam pendentes no
   *buffer* e voltam a ser enviados, por isso nada se perde. O atraso aleatório espalha as novas tentativas
   (evita que 1.000 agentes voltem todos no mesmo segundo).
3. O controlo de admissão corre **antes da autenticação**: um pedido rejeitado não chega a consultar a base de
   dados. A métrica `monitor_ingest_inflight` mostra a ocupação, e as rejeições aparecem no histograma de
   pedidos com o código `ResourceExhausted` (ADR-0004).
4. **Justiça por host: não implementada agora.** Fica desenhada (*token bucket* por host em memória por
   instância) com o gatilho: atraso p95 dos restantes hosts > 1 s em SC5, ou um host a ocupar mais de metade
   das admissões. O *jitter* inicial nos *workers* do remote também fica de fora: o `RetryInfo` aleatório já
   espalha as novas tentativas.

## Fundamentação teórica
* **Performance → *Limit Event Response*, *Bound Queue Sizes*, *Schedule Resources***: a ingestão tem uma quota
  fixa do recurso partilhado.
* **Availability → *Degradation***: sob sobrecarga, a ingestão fica mais lenta para o *dashboard* continuar
  utilizável; combina com *Retry* no remote (o que torna a degradação segura).
* ***Generate and test*** (slide 06): a medição retirou uma parte do desenho (justiça por host) que a análise
  tinha proposto.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Esperar por uma vaga (fila em memória) em vez de rejeitar | Os pedidos em espera ocupam memória e *goroutines* e chegam ao *timeout* do agente; rejeitar com `RetryInfo` devolve a espera ao agente, que já guarda os dados |
| *Pool* separado para o *dashboard* | Duas *pools* para a mesma base de dados complicam a configuração (e D8 multiplica-as por instância); limitar a ingestão tem o mesmo efeito |
| Fila/broker à frente da BD | Evolução E1 para 10.000+ hosts, com gatilho; a 1.000 hosts é infraestrutura a mais |
| Só limite por host | Não protege contra o agregado de 1.000 hosts, que é o problema medido |

## Consequências
* **Positivas:** o *dashboard* tem sempre ligações disponíveis; a sobrecarga deixa de se propagar à base de
  dados; nenhum dado se perde, porque o agente guarda e repete.
* **Negativas / trade-offs:** a recuperação fica mais lenta (os agentes esperam o `RetryInfo`), dentro do limite
  de 15 min de SC2. O limite é por instância: com N instâncias (D8) o total é N × 15, o que obriga a dimensionar
  `INGEST_MAX_INFLIGHT` com `max_connections` do PostgreSQL.

## Verificação
* Teste: com o limite atingido, o pedido seguinte recebe `RESOURCE_EXHAUSTED` com `RetryInfo` entre 1 e 10 s e
  não chega a autenticar; a configuração rejeita um limite maior ou igual ao *pool*.
* Carga (`iter-4` contra `iter-3`): SC2 com p95 do *dashboard* < 1 s durante a recuperação, *backlog* absorvido
  em ≤ 15 min, 0 perdas e 0 duplicados; SC1 e SC5 continuam cumpridos.
