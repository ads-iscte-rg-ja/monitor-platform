# ADR-0014: *Handlers* testáveis com interfaces mínimas; relógio e fuso horário injetados

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Testability
* **Cenários relacionados:** TE2, TE3; lacunas M5, M6
* **Decisão do plano:** D14 (`../PLANO_MELHORIAS.md` §7.3)

## Contexto
**Os *handlers* não se testam sozinhos (M5, TE2).** Cada *handler* do central guarda um serviço concreto
(`*services.AlertsService`, `*services.HostsService`, …) e o `*session.SessionManager`. Testar um *handler*
obriga a montar o serviço real, o repositório e um PostgreSQL. Resultado (medido a 21/11): **cobertura de
`internal/handlers` 9,5 %**, com só dois ficheiros de teste (*login* e `/health`). É a camada que traduz
formulários, códigos HTTP e redirecionamentos, e é a que muda quando a interface muda.

**O tempo está escondido (M6, TE3).** 16 chamadas diretas a `time.Now()` no central e 14 no remote; o fuso
`Europe/Lisbon` está fixo em 4 sítios (`services/alerts.go:62,240`, `services/error_logs.go:61`,
`server/jobs.go:152`), carregado a cada pedido ou a cada ciclo. O resumo diário de alertas decide a hora de
envio com o relógio da máquina, e nada permite testá-lo sem esperar. O remote já injeta o relógio onde a lógica
depende dele (ADR-0011), mas ainda há um `time.Sleep` num teste (`sender/pause_test.go:289`), à espera de que a
fila esvazie.

## Decisão
1. **Cada *handler* declara a interface mínima de que precisa** (*accept interfaces, return structs*), no
   próprio ficheiro: só os métodos que chama. Os construtores passam a aceitar essas interfaces; os serviços
   concretos satisfazem-nas sem mudar, e `server.go` não muda. A sessão entra pela interface com os métodos
   usados (`GetInt`, `LoginUser`, `Destroy`).
2. **Testes dos *handlers* com *fakes* escritos à mão** e as páginas reais (`frontend/`): cada teste verifica o
   código HTTP, o redirecionamento, o que chega ao serviço e o que é desenhado. Os modelos HTML são executados de
   verdade, o que também apanha um campo que um modelo use e o *handler* não passe.
3. **Relógio injetado** onde o tempo decide alguma coisa: o resumo diário (quando enviar e de que dia) e a hora
   de disparo dos alertas. Um `func() time.Time` por omissão `time.Now`, como no remote (ADR-0011).
4. **`APP_TIMEZONE`** (por omissão `Europe/Lisbon`), carregada e validada **uma vez** no arranque; o serviço de
   alertas, o de erros e o resumo diário recebem o `*time.Location`. Um fuso inválido impede o arranque.
5. **Sem `time.Sleep` nos testes:** o teste do remote passa a esperar por um sinal do central falso.

## Fundamentação teórica
* **Testability → *Abstract Data Sources* / *Specialized Interfaces*:** o *handler* depende de uma interface
  com o que usa, e o teste dá-lhe uma implementação controlada.
* **Testability → *Limit Nondeterminism*:** relógio injetado; fuso explícito; testes que esperam por eventos.
* **Modifiability → *Defer Binding*:** o fuso passa a ser configuração lida no arranque.
* Princípio de segregação de interfaces (ISP): cada cliente vê só o que usa.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| *Mocks* gerados (gomock, mockery) | Mais uma ferramenta e testes acoplados à ordem e à forma das chamadas; os *fakes* à mão são poucas linhas por interface |
| Testar os *handlers* só ponta a ponta (com PostgreSQL) | Lento e não isola a camada: uma falha não diz se foi o *handler*, o serviço ou a consulta |
| Interfaces grandes no pacote `services` (uma por serviço, com todos os métodos) | Quem implementa decide o contrato; um *fake* teria de implementar métodos que o *handler* nunca chama |
| Um tipo `Clock` com interface e várias implementações | Um `func() time.Time` chega e é o que o remote já usa; uma interface não traria nada |
| Substituir todas as 16 chamadas a `time.Now()` | Muitas só carimbam um registo ou medem uma duração (métricas, *slug*, ano no rodapé): injetá-las não torna nenhum teste possível que hoje não seja |

## Consequências
* **Positivas:** a camada HTTP testa-se em milissegundos, sem base de dados; mudar um formulário ou uma página
  tem teste; o resumo diário testa-se para qualquer dia e hora; o fuso muda sem recompilar.
* **Negativas / *trade-offs*:** uma interface pequena por *handler* (7 interfaces); um método novo num serviço
  usado por um *handler* obriga a acrescentá-lo à interface (o compilador avisa). Os *fakes* não provam que o
  serviço real se comporta como eles: isso continua nos testes dos serviços e de integração.

## Verificação
* **TE2:** cobertura de `internal/handlers` ≥ 60 % (era 9,5 %).
* **TE3:** 0 `time.Sleep` nos testes dos quatro repositórios (era 1); o resumo diário com relógio controlado:
  não envia antes da hora, envia uma vez à hora certa, com a data no fuso configurado.
* `APP_TIMEZONE` inválido recusado no arranque; `Europe/Lisbon` só aparece como valor por omissão.

**Resultado (21/11):** TE2 e TE3 cumprem-se (`docs/metrics/iter-6/te2-te3-mo2.md`). Cobertura de
`internal/handlers`: **9,5 % → 95,6 %**, com testes de todos os *handlers* (≈ 0,2 s, sem base de dados). `time.Sleep`
nos testes: **1 → 0**. O resumo diário tem 6 casos com relógio e fuso controlados, incluindo a mudança de hora.
`Europe/Lisbon` no código: 4 → 1 (o valor por omissão). O binário leva a base de fusos (`time/tzdata`), para
`APP_TIMEZONE` funcionar numa máquina sem `tzdata`. Lint do central igual (53); cobertura das linhas novas 90,5 %.

## Histórico
