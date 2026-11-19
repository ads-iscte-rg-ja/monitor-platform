# ADR-0007: Central com várias instâncias: liderança por *job*, limites partilhados e balanceador

* **Estado:** Aceite
* **Data:** 2026-11-19
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Scalability (com Availability)
* **Cenários relacionados:** SC3; lacunas S5, S6
* **Decisão do plano:** D8 (`../PLANO_MELHORIAS.md` §7.2)

## Contexto
SC3 pede que o débito suba ao acrescentar instâncias do central e que cada *job* de fundo corra numa só.
Hoje, cada instância corre todos os *jobs* (S5) e conta as tentativas de login na sua memória (S6).

A análise do código mostrou que os *jobs* já são **corretos** com várias instâncias, porque cada um é
idempotente: a retenção usa um *lock* transacional, o *outbox* usa `FOR UPDATE SKIP LOCKED`, um alerta só
abre um incidente (índice único), o resumo diário tem chave de deduplicação e o resultado de uma verificação
de saúde só é gravado se for mais recente do que o anterior. O problema de S5 é o **custo**: com N instâncias,
cada *host* recebe N verificações de saúde a cada 30 s e as regras de alerta são avaliadas N vezes. Já S6 é um
problema de segurança: com N instâncias, o limite de tentativas de login passa a ser N vezes maior.

O desenho revelou um terceiro problema, que o plano não previa: atrás de um balanceador, todos os pedidos
chegam ao central com o endereço do balanceador. O limite **por IP** passaria a ser um limite global, e um
atacante bloquearia o login a todos os utilizadores.

## Decisão
1. **Liderança por *job* com `pg_try_advisory_lock`.** Cada instância reserva uma ligação do *pool* para a
   liderança. Antes de cada execução de um *job*, a instância tenta obter o *lock* do *job* nessa ligação. Se
   o obtiver, passa a ser o líder e mantém-no enquanto a sessão existir; se não, salta a execução. O *lock* é
   de sessão: se a instância morre, o PostgreSQL liberta-o e outra instância assume na execução seguinte, ou
   seja, em menos de um intervalo do *job* (5 s para as notificações, 15 s para os alertas, 30 s para a
   saúde). Num encerramento ordenado, a instância fecha a sessão e liberta os *locks* de imediato. A métrica
   `monitor_job_leader{job}` mostra que instância lidera cada *job*.
2. **A idempotência continua a ser a garantia de correção.** A liderança evita trabalho repetido, mas não é
   usada para garantir a correção: se a ligação de liderança cair a meio de uma execução, outra instância
   pode começar antes de a primeira acabar, e a idempotência de cada *job* torna essa sobreposição inofensiva.
3. **`APP_ROLE=all|web|worker`.** `web` serve o HTTP e a ingestão gRPC e não corre *jobs*; `worker` corre os
   *jobs* e serve apenas `/health`. Por omissão é `all`, e o *deploy* de uma instância fica como estava.
4. **Limitador de login no PostgreSQL.** A tabela `login_attempts` guarda uma janela fixa de um minuto por
   chave (IP e conta, com *hash* SHA-256). Cada tentativa faz um único `INSERT … ON CONFLICT DO UPDATE` para as
   duas chaves, por isso o limite é o mesmo qualquer que seja o número de instâncias. O login é raro, e um
   *upsert* por tentativa é barato. O job de retenção apaga as janelas expiradas. O limite de *bcrypt* em
   simultâneo continua local, porque protege o CPU de cada instância.
5. **Proxies de confiança (`TRUSTED_PROXIES`).** Só os pedidos que chegam de um endereço desta lista têm o
   IP do cliente lido de `X-Forwarded-For`, e o nginx substitui esse cabeçalho em vez de lhe acrescentar
   valores. Sem configuração, o comportamento anterior mantém-se: o cabeçalho nunca é lido.
6. **nginx como balanceador**, no Compose (`docker compose up --scale backend=3`), para o HTTP e para o gRPC.
   Usa `grpc_pass`: o nginx termina o HTTP/2 do agente e distribui **cada pedido**, e não cada ligação, pelas
   instâncias. O `upstream` volta a resolver o nome do serviço, o que lhe permite encontrar as réplicas
   criadas pelo `--scale`, e retira uma instância que falha durante algum tempo (verificação passiva). As
   sessões já estão no PostgreSQL, por isso não é preciso *sticky sessions*.
7. **`POSTGRES_MAX_OPEN_CONNS` passa a 20 por omissão** (por isso `INGEST_MAX_INFLIGHT` passa a 12). Três
   instâncias usam no máximo 60 das 100 ligações do PostgreSQL.

## Fundamentação teórica
* **Performance → *Increase Resources*, *Maintain Multiple Copies of Computations***: as instâncias web são
  réplicas sem estado (o estado está no PostgreSQL), atrás de um *intermediary* (o balanceador).
* **Availability → *Active Redundancy*** (instâncias web) e ***Passive Redundancy*** (o líder de cada *job*
  tem instâncias em espera, que assumem quando ele falha).
* **Modifiability → *Defer Binding***: o papel de cada instância (`APP_ROLE`) e o número de instâncias são
  escolhidos no *deploy*, sem mudar o código.
* **Security → *Limit Access*** e **Resist attacks**: o limite de login é global, e o IP do cliente só é
  aceite de um proxy conhecido.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Coordenador externo (etcd, Consul, Redis) | Mais uma peça de infraestrutura; o PostgreSQL já oferece *locks* com a semântica certa |
| Um *lock* por execução (`pg_try_advisory_xact_lock`, como a retenção já fazia) | Os temporizadores das instâncias não estão sincronizados: cada uma obtém o *lock* noutro momento, e o *job* corre N vezes por ciclo |
| Separar já os *jobs* num serviço próprio | `APP_ROLE=worker` dá o mesmo isolamento sem mais um binário nem mais um repositório |
| Redis para o limitador de login | Mais uma dependência por uma operação rara; o PostgreSQL chega |
| Balanceador de nível 4 (TCP) | O gRPC mantém uma ligação HTTP/2 por agente: cada agente ficaria preso a uma instância, e o balanceamento seria por ligação e não por pedido |
| Ler `X-Forwarded-For` de qualquer pedido | Qualquer cliente poderia escolher o IP que o limitador vê |

## Consequências
* **Positivas:** o débito pode subir com mais instâncias. Cada *job* tem um único executor e um substituto
  automático. O limite de login é igual com 1 ou N instâncias. O *deploy* de uma instância não muda.
* **Negativas / *trade-offs*:**
  * O PostgreSQL continua a ser um **ponto único** (falha e capacidade), aceite para 1.000 hosts; as réplicas
    e a alta disponibilidade da base de dados ficam como evolução (plano §8, E4).
  * Cada instância usa uma ligação do *pool* para a liderança.
  * A troca de líder depende de o PostgreSQL detetar que a sessão morreu. Se o processo termina, isso é
    imediato; numa partição de rede, depende do *keepalive* TCP do servidor.
  * O nginx é mais um ponto único no Compose. Em produção, o balanceador seria redundante ou gerido.
  * O limite de admissão de ADR-0006 é por instância: N instâncias admitem N × 12 pedidos em simultâneo, e a
    base de dados recebe N vezes mais concorrência. Com várias instâncias, `INGEST_MAX_INFLIGHT` deve ser o
    orçamento total da ingestão a dividir por N (por exemplo, 12 / 3 = 4), e não o valor por omissão.

## Verificação
* Integração (PostgreSQL real): dois *electors* para o mesmo *job*, só um lidera; o líder fecha a sessão e o
  outro assume; o limite de login é partilhado por dois `AuthService`; a migração para a versão 4.
* Unitários: `APP_ROLE`, `TRUSTED_PROXIES` (um cabeçalho de um cliente desconhecido é ignorado), *jobs* que
  saltam a execução sem liderança.
* Carga (SC3): o mesmo teste com 1, 2 e 3 instâncias, com débito ≥ 1,8× e ≥ 2,5×, uma única instância a
  executar cada *job* em cada ciclo, e troca de líder em ≤ 30 s depois de matar o líder.
