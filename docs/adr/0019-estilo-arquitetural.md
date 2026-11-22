# ADR-0019: Estilo arquitetural: agentes *store-and-forward* e um central monolítico em camadas, replicado sobre uma base de dados partilhada

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** todos (é a decisão de que os outros ADR partem)
* **Cenários relacionados:** SC1–SC5, AV1, MO1–MO3, IO1
* **Decisão do plano:** D20 (`../PLANO_MELHORIAS.md` §7.6)

## Contexto
Os ADR-0003 a 0018 e 0020 a 0023 tratam um atributo de cada vez. Nenhum diz **que estilo** o sistema segue nem
**porquê**, e essa é a primeira decisão que o slide 08 pede: *"monolith vs distributed, where should data live,
synchronous vs asynchronous communication"*. O estilo estava no código desde a iteração 0 e foi recuperado na
reconstrução da arquitetura (relatório, cap. 3). Este ADR regista-o com os critérios de decisão do slide 08, e
junta numa vista única duas grelhas do mesmo slide que o projeto já aplicava sem lhes dar nome: as falácias da
computação distribuída e a conascência.

Os critérios de decisão do slide 08, aplicados ao Monitor:

| Critério | No Monitor |
|---|---|
| Domínio | Telemetria com picos imprevisíveis (logs), recolhida em muitos *hosts*; um *dashboard* de leitura e alertas por email |
| Características arquiteturais | Escalabilidade (1.000 *hosts*), disponibilidade (não perder nada com o central em baixo), manutenção (relatório, cap. 4) |
| Arquitetura de dados | O registo e o recibo de deduplicação na mesma transação ACID (ADR-0018, 0020) |
| Fatores organizacionais | 2 pessoas; prazo de 3 semanas; sem serviços geridos |
| Processo e operação | *Deploy* em Docker Compose; sem orquestrador; CI partilhado (ADR-0002) |
| Isomorfismo domínio/arquitetura | Os *hosts* estão distribuídos por natureza; o processamento central não |

## Decisão
**O sistema é distribuído com duas unidades de *deployment*** (slide 08), e cada uma segue o estilo que lhe
serve:

1. **O agente** (`monitor-remote`, um por *host*, mais o SDK nas aplicações) é um ***pipeline*** com um *pipe*
   persistente: a recolha e o SDK produzem registos, o *buffer* SQLite guarda-os, os *workers* de envio
   consomem-nos (ADR-0020, 0021). Cada *filter* faz uma coisa e não conhece os outros (as regras do `depguard`
   impedem `requests` e `repository` de se usarem um ao outro).
2. **O central** (`monitor-central`) é um **monólito em camadas** (*handlers* → *services* → *repositories*), com
   **partição técnica** e as regras de camadas verificadas pelo `depguard`. Os ***jobs* de fundo** (disponibilidade
   dos *hosts*, alertas de disponibilidade e de métricas, envio de emails, resumo diário, retenção) correm **no
   mesmo processo**.
3. **O central replica-se horizontalmente sobre uma base de dados partilhada:** N instâncias sem estado atrás
   do nginx, cada *job* numa só instância por eleição de líder (ADR-0007). O `APP_ROLE` (`all`, `web`,
   `worker`) já permite separar as instâncias que servem pedidos das que correm *jobs*, sem mudar o código.
4. **Dentro do central, os alertas são um microkernel:** um núcleo genérico (o avaliador) e as métricas como
   *plug-ins*, obtidos pelo nome a partir de um **registo**, com ligação em tempo de compilação (ADR-0008). É
   o exemplo do *plug-in registry* do slide 08. O microkernel é o único estilo que pode ter partição técnica e
   por domínio ao mesmo tempo, e é isso que torna uma métrica nova uma alteração num só módulo (MO1).
5. **Comunicação:** **síncrona por pedido** entre agente e central (gRPC, ADR-0003), mas **assíncrona do ponto
   de vista da aplicação**, que só escreve no *buffer* local e nunca espera pela rede. Não há *broker* (E1).
6. **Interface feita no servidor:** *templates* Go (MVC no servidor), um pouco de JavaScript sem *build* (o
   *dashboard* atualiza-se a cada 15 s e pára quando o separador está escondido) e Tailwind servido localmente
   (ADR-0016). A apresentação vive em `frontend/` e nos *handlers*, nunca nos serviços nem nos repositórios
   (`depguard`), que é o que MO3 mede.
7. **Go** em todos os componentes: um binário estático por componente, concorrência nativa para os *workers* e
   as *probes*, e uma só cadeia de ferramentas para o CI e a análise estática (ADR-0002).

### As oito falácias da computação distribuída (slide 08)
Cada fronteira de rede do sistema assume estas falácias como falsas, e cada uma tem uma resposta medida ou
uma decisão registada:

| Falácia | Resposta no Monitor | ADR |
|---|---|---|
| 1. A rede é fiável | *Store-and-forward*, *retry* com *backoff* e *jitter*, recibos idempotentes; AV1: 0 perdas em 1 h | 0020, 0011 |
| 2. A latência é zero | Lotes de até 100 registos; a aplicação escreve localmente e não espera | 0005, 0021 |
| 3. A largura de banda é infinita | Lote ≤ 1 MiB; Protocol Buffers; amostragem na origem como evolução (E8) | 0003 |
| 4. A rede é segura | Chave por *host* (HMAC), TLS no *ingress*, guarda SSRF nas *probes* | 0023, 0016 |
| 5. A topologia não muda | Instâncias sem estado atrás do nginx; liderança por *job*; endereço do central validado | 0007, 0015 |
| 6. Há um só administrador | O estado do *buffer* de cada *host* chega ao central (o operador do central vê o que se passa num *host* que não administra); `/health/ready` | 0010 |
| 7. O custo de transporte é zero | Protocol Buffers em vez de JSON; lotes. **Não foi medido:** é um argumento, não uma medição | 0003 |
| 8. A rede é homogénea | Contrato `.proto` independente da linguagem; o gerador de carga k6 (JavaScript) é um agente feito só a partir dele (IO1) | 0003 |

Os outros desafios que o slide 08 aponta aos sistemas distribuídos:
* **Transações distribuídas: evitadas.** Remote e central têm cada um a sua transação local, e a idempotência
  do recibo fecha a lacuna entre elas (ADR-0020). O email segue o mesmo princípio com a *outbox* (ADR-0022).
  Não há 2PC nem *saga*.
* **Manutenção e versionamento de contratos:** o `.proto` vive num repositório próprio, com *tags* semânticas e
  `buf breaking` no CI (ADR-0003); o SDK tem versões semânticas (`v0.2.0`).
* **Logs distribuídos:** são estruturados e com `request_id` no central (ADR-0004), mas **não há correlação entre
  um pedido do remote e o seu tratamento no central**. É uma lacuna assumida, com o gatilho E6
  (OpenTelemetry).

### Conascência (slide 08)
A conascência mede o acoplamento pelo que tem de mudar em conjunto. As decisões de manutenção do projeto
reduzem-na ou trocam formas fortes por formas mais fracas e verificáveis:

| Onde | Antes | Depois | ADR |
|---|---|---|---|
| Remote → central: porque é que um lote foi rejeitado | **de significado** (o remote decidia pelo texto, em inglês, das mensagens de erro) | **de nome e de tipo** (um `enum` `RejectionReason` no `.proto`, verificado pelo compilador e pelo `buf`) | 0003 |
| Níveis de log | **de valores** (a mesma lista em 10 sítios, que tinham de mudar juntos) | uma fonte única por repositório e testes de consistência entre repositórios | 0015 |
| Uma métrica de alerta nova | **de algoritmo e de valores** espalhada por 7 sítios em 5 ficheiros e 3 camadas | concentrada num *plug-in*, com o nome como única ligação ao núcleo | 0008 |
| SDK → *buffer* do remote | **de nome e de tipo** sobre o esquema, entre dois repositórios | igual, mas com dono definido (o remote) e testes contra o mesmo `schema.sql` | 0021 |
| Deduplicação | **de identidade** (`host_id` + `source_id`, partilhados por remote e central) | igual: é a essência do recibo, e está no contrato | 0020 |
| Liderança dos *jobs*; `RetryInfo` | **dinâmica**, de execução e de tempo | encapsulada (eleição por *advisory lock*; o remote espera o maior entre o seu *backoff* e o pedido do central) | 0007, 0006 |

### Variabilidade (slide 07)
O Monitor não é uma linha de produtos, e o relatório não o apresenta como tal. Usa, ainda assim, quatro dos
mecanismos de variação do slide 07:
* um ***extension point***: o registo das métricas de alerta (ADR-0008);
* **parâmetros e configurador:** toda a configuração por ambiente, validada no arranque, incluindo o papel da
  instância (`APP_ROLE`);
* **substituição de componentes:** o relógio, o fuso horário e o `Dialer` das *probes* são injetados (ADR-0014,
  0016);
* um ***core asset* reutilizável:** o SDK, usado por qualquer aplicação Go (o hello-world é a primeira).

## Fundamentação teórica
* **Estilos e critérios de decisão** (slide 08): monólito em camadas, *pipeline*, microkernel; monólito vs
  distribuído, onde vivem os dados, comunicação síncrona ou assíncrona.
* **Falácias da computação distribuída e desafios dos sistemas distribuídos** (slide 08).
* **Conascência estática e dinâmica** (slide 08): *"reducing connascence will reduce the cost of change"*.
* **Variabilidade** (slide 07).
* **Padrões Layered, Client-Server, Shared-Data e MVC** (slide 04), e as táticas de cada ADR.
* **Arquitetura e implementação** (slide 07): as camadas estão no código (regras do `depguard`, comentários de
  pacote), o que é *conformance by analysis*.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| **Microserviços** (ingestão, alertas, *dashboard*, notificações, cada um com a sua base de dados) | O registo, o recibo e a avaliação de alertas partilham uma transação; o slide 08 diz que *"transaction boundaries are an indicator of service granularity"*, e separá-los exigiria uma *saga*. *"MS couldn't exist without DevOps"*, o que uma equipa de 2 não sustenta. Cada fronteira de rede nova traz as 8 falácias. Os limites a 1.000 *hosts* resolveram-se com táticas locais (ADR-0005, 0006, 0013, 0017) |
| ***Service-based*** já (`ingest`, `web` e `worker` em *deploys* separados, a mesma base de dados) | É o passo seguinte, e o `APP_ROLE` já o prepara. Fica como **E3**, com o gatilho "ingestão e *dashboard* a competir pelo CPU", que as medições não mostraram (CPU do central ≤ 16 % em SC4, na medição final da iter-7) |
| ***Event-driven* com *broker*** (Kafka, NATS) entre a API e a base de dados | O *store-and-forward* com recibos já dá *at-least-once* sem duplicados; na topologia *broker*, o tratamento de erros é difícil e não há recuperação da transação (slide 08). Fica como **E1**, com gatilho |
| **SOA orquestrada** | O slide 08 apresenta-a como o exemplo dos limites da partição técnica levada ao extremo |
| ***Space-based*** (dados em memória replicados) | Pensado para elasticidade com picos de utilizadores; aqui o estado tem de ser durável e transacional |
| ***Jobs* num processo separado** desde o início | Mais uma unidade de *deployment* sem um ASR que a pague; o `APP_ROLE=worker` dá essa separação quando for preciso |
| **SPA** (React, Vue) no lugar dos *templates* | Um passo de *build* e uma API JSON completa a manter, para páginas que são sobretudo leitura. MO3 continua mensurável com os *templates* |
| Outra linguagem (Java, Python, Node) | Go dá binários estáticos sem *runtime* no *host* monitorizado e concorrência barata para os *workers*. O contrato `.proto` permite agentes noutras linguagens (IO1) |

## Consequências
* **Positivas:**
  * Uma só base de dados e transações locais: as garantias de integridade não dependem de coordenação.
  * A partição técnica do central é simples e conhecida. As regras de camadas são verificadas em cada PR, e o
    microkernel dos alertas dá partição por domínio onde ela mais importa (MO1).
  * Os caminhos de evolução estão identificados, com gatilhos (E1, E3, E9), sem reescrita.
* **Negativas / *trade-offs*:**
  * A **partição técnica** espalha cada funcionalidade pelas três camadas. Para os alertas, o microkernel
    resolveu-o (MO1); para o resto, é o custo aceite do estilo em camadas (slide 08: *"maintainability,
    testability, deployability adversely affected when apps grow"*).
  * A base de dados partilhada é o estrangulamento das escritas e um ponto único de falha (ADR-0018, SC3).
  * Um ADR retroativo descreve uma decisão que não foi tomada com este vocabulário, e diz isso aqui.

## Verificação
* As regras de camadas (`depguard`) passam em cada PR: é a conformidade do estilo, verificada por análise.
* O que a análise estática não vê, porque é estrutura de execução, verifica-se em execução: cada *job* numa só
  instância (SC3), o caminho remote → central sem perdas (AV1, E2E).
* **MO3** (uma alteração de apresentação não toca em `services` nem `repositories`) e **IO1** (um agente feito
  só a partir do `.proto`) são as medidas diretas de dois pontos deste ADR; os resultados ficam no relatório
  (cap. 7).

## Histórico
