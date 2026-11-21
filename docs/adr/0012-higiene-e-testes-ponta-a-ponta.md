# ADR-0012: Higiene dos repositórios e testes ponta a ponta em Compose

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Testability, Availability
* **Cenários relacionados:** AV1, SE1, MN1 (ponta a ponta); lacunas M8, M9, M10
* **Decisão do plano:** D15 (`../PLANO_MELHORIAS.md` §7.3)

## Contexto
Dois problemas diferentes, resolvidos no mesmo passo porque ambos preparam os repositórios para serem
usados por quem não os escreveu.

**Higiene (M8–M10).**
* `monitor-remote/internal/collect/error_logs.go` (`ErrorLogCollector`, 184 linhas, mais 224 de teste) não é usado por nenhum
  binário: os logs entram no *buffer* pelo SDK (`monitor-go-sdk`, `LogError`). São duas validações dos
  mesmos campos que podem divergir (M8).
* `monitor-central/internal/server/routes.go` mantém à mão a lista `protectedPaths`, paralela ao grupo de
  rotas com `mdw.Auth`. Já divergiu: `/api/v1/dashboard/summary` e `/profile/notification-email` estão
  protegidas, mas o log de arranque só as marca como tal por coincidência de prefixo (M9).
* O módulo do SDK chama-se `github.com/rmg-unicage/monitor-go-sdk`, uma conta que não é a da organização onde
  os repositórios vivem (`ads-iscte-rg-ja`); os READMEs do central, do remote e do SDK apontam para um
  `go.work` e um `IMPLEMENTATION_CHECKLIST.md` que não existem (M10). A LICENSE (MIT) e os testes do SDK já
  foram feitos na iteração 1 (cobertura do SDK: 89,3 %).

**Nenhum teste junta os componentes.** Os testes de cada repositório substituem o outro lado por *fakes*
(o remote fala com um servidor gRPC de teste; o central recebe pedidos construídos no teste). AV1 ("central
em baixo → 0 perdas, 0 duplicados") e SE1 ("chave inválida ou revogada → nada persistido") são propriedades
do sistema inteiro: dependem do SDK, do *buffer* SQLite, da retentativa do remote, do balanceador, da
autenticação e da idempotência do central ao mesmo tempo. O plano marca-os como "já cumpridos, falta
prová-los" (§3.2). MN1 está provado nos dois lados separadamente (ADR-0010), não ponta a ponta.

## Decisão
**Higiene**
1. Remover `ErrorLogCollector` (e o seu teste). O SDK é o único caminho de escrita de logs no *buffer*.
2. As rotas autenticadas passam a ser **uma tabela** (`protectedRoutes`: método, padrão, *handler*) registada
   dentro do grupo com `mdw.Auth`. O log de rotas e um teste derivam dela; deixa de haver uma segunda lista.
   O teste percorre a tabela e confirma que cada rota, sem sessão, redireciona para `/login` (ou responde 401, nas `/api/`).
3. Módulo do SDK: `github.com/ads-iscte-rg-ja/monitor-go-sdk`. O hello-world mantém o `replace` para o
   repositório irmão até haver uma *tag* publicada (como o `monitor-api` antes da v1.0.0).
4. `go.work` local na raiz do espaço de trabalho, criado por `monitor-platform/scripts/go-work.sh` (a raiz não
   é um repositório). O CI e os Dockerfiles continuam com `GOWORK=off`: cada repositório compila sozinho.
5. READMEs corrigidos (sem referências a ficheiros que não existem).

**Testes ponta a ponta** (`monitor-platform/e2e/`)
1. **Compose** com o sistema real, construído a partir dos repositórios irmãos: PostgreSQL, migrações,
   central, nginx (o balanceador do ADR-0007, **com TLS**), remote e hello-world (SDK). O certificado de
   teste é gerado a cada execução; o remote confia nele por `SSL_CERT_FILE`. Assim o remote usa
   `https://` como em produção (só aceita `http://` em *loopback*).
2. **Um condutor em Python** (só biblioteca padrão, como as ferramentas do `loadtest/`) provisiona os hosts
   (digest HMAC, como em `loadtest/provisionar.py`), gera logs com o hello-world, para e arranca serviços e
   verifica o estado no PostgreSQL e no SQLite. Cada cenário escreve o resultado (medido, limite, passa/falha)
   em `e2e/resultados/<data>.json`.
3. **Cenários:**
   * **caminho feliz:** N logs do hello-world e as estatísticas do remote chegam ao central;
   * **AV1:** `docker compose kill` do central (sem paragem graciosa) com o balanceador vivo; o hello-world
     gera N logs; o central volta. Passa se o PostgreSQL tiver exatamente os registos do *buffer*
     (mesmo conjunto de `source_id`, logs e estatísticas), 0 duplicados e 0 pendentes ou em quarentena no
     remote; mede-se o tempo até tudo estar entregue;
   * **SE1:** um segundo remote com uma chave **inválida** e depois com a chave de um host cuja chave foi
     **revogada** (regenerada, como faz `RegenerateAPIKey`). Passa se nada for gravado no central para esse
     host, o remote pausar (`UNAUTHENTICATED`, ADR-0011) e os registos continuarem pendentes no *buffer*;
   * **MN1:** um registo pendente é corrompido no *buffer*; passa se o central mostrar `quarantined = 1`
     para o host em ≤ 1 ciclo de estatísticas depois da quarentena.
4. **Intervalos curtos** no remote (estatísticas a cada 5 s, logs a cada 2 s) e paragem de 60 s por omissão
   (`--paragem` aceita outra duração, por exemplo 1 h). A duração não muda o mecanismo, só o tamanho do
   *buffer*, que é limitado e testado à parte (AV4, ADR-0009).
5. **Workflow noturno** no `monitor-platform` (`e2e.yml`: `schedule` diário e `workflow_dispatch`): faz
   *checkout* dos repositórios irmãos no `main` e corre todos os cenários. Não é obrigatório nos PRs: demora
   minutos e depende do `main` de seis repositórios; falha visível no dia seguinte chega para um sistema
   deste tamanho.

## Fundamentação teórica
* **Modifiability → *Refactor* e *Reduce Size of a Module*:** código morto e listas paralelas são duas
  fontes da mesma verdade; remover uma reduz o que é preciso mudar e rever.
* **Testability → *Sandbox*:** o sistema corre isolado, num Compose descartável, com dados e chaves de teste.
* **Testability → *Specialized Interfaces* / *Record/Playback*:** o condutor observa o estado nos dois lados
  (PostgreSQL e SQLite) em vez de confiar em mensagens de log.
* **Testability → *Limit Nondeterminism*:** os cenários esperam por condições (com prazo), nunca por tempos
  fixos; os intervalos do remote são configurados curtos para o teste caber em minutos.
* **Availability → *Detect Faults*:** AV1 e SE1 provam ponta a ponta as táticas que já existem
  (*store-and-forward*, *Retry*, idempotência por recibos; autenticação e pausa).

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| E2E em Go com `testcontainers-go` | Mais uma dependência grande, num repositório (`monitor-platform`) que não tem código Go de produção; o Compose já é a forma de executar o sistema (central, `loadtest/`) e o condutor só orquestra e consulta |
| Remote com `http://` direto ao central (sem TLS) | O remote recusa-o fora de *loopback*, de propósito (ADR-0003); abrir uma exceção só para o teste deixava o caminho de produção (TLS + balanceador) por testar |
| Remote no *namespace* de rede do central, para usar `localhost` | Parar o central (AV1) destrói o *namespace* e o remote perde a rede: o teste deixava de representar uma falha do central |
| E2E obrigatório em cada PR | Minutos por PR e dependência do `main` de seis repositórios; o noturno apanha regressões com um dia de atraso, aceitável aqui |
| Revogar a chave pela UI (login, CSRF, formulário) | Testa a UI, não SE1; o condutor faz a mesma alteração que `RegenerateAPIKey` (novo digest na linha do host) |
| Manter `protectedPaths` e testar que coincide com as rotas | Continua a haver duas listas; o teste só avisa da divergência, a tabela única impede-a |

## Consequências
* **Positivas:** AV1, SE1 e MN1 passam a ter prova ponta a ponta, repetível e com resultado guardado; o
  sistema corre inteiro num comando (útil para demonstrações); menos código morto e uma lista a menos.
* **Negativas / *trade-offs*:**
  * O E2E corre com intervalos mais curtos do que os de produção (30 s): prova o mecanismo, não a cadência.
    A cadência de produção está nos testes com relógio injetado (AV3, MN2).
  * O noturno depende de serviços externos (imagens Docker, GitHub); uma falha de infraestrutura aparece
    como falha do E2E. O relatório de cada execução distingue "não arrancou" de "cenário falhou".
  * O módulo do SDK muda de nome: quem o importava tem de mudar o *import*. Só o hello-world o usa.

## Verificação
* **AV1:** 0 registos perdidos e 0 duplicados (logs e estatísticas), com o central morto 60 s e N = 500 logs.
* **SE1:** 0 linhas gravadas para a chave inválida e para a revogada; registos pendentes intactos no *buffer*.
* **MN1:** quarentena visível no central em ≤ 1 ciclo de estatísticas.
* Higiene: `grep` sem `ErrorLogCollector` nem `rmg-unicage`; teste das rotas protegidas; lint e cobertura
  como no CI.
* **E2E verde no CI noturno.**

**Resultado (21/11):** os cinco cenários passam (`docs/metrics/iter-6/e2e/`). Com N = 500 e o central morto
63 s: **AV1** compara o *buffer* inteiro, 1.000 logs (500 do caminho feliz e 500 gerados com o central em
baixo) e 18 estatísticas: todos no central, 0 perdidos, 0 duplicados,
0 sem origem, 0 pendentes no fim; a entrega completa 36,7 s depois de o central voltar (a espera do
*backoff* do remote já ia em cerca de 40 s). **SE1** com a chave inválida e com a revogada: pausa por `UNAUTHENTICATED` em 0,7 s, 0
linhas no central, os 10 logs e a estatística pendentes no *buffer*. **AV1 com 1 h** em baixo (3.603 s): 1.000 logs e 634 estatísticas, 0 perdidos, 0 duplicados,
entrega completa 202 s depois (o *backoff* chega a 5 min). **MN1**: 5,85 s, 0,16 s e 5,82 s em três execuções,
para um limite de 7 s (o atraso depende da fase entre a quarentena e a recolha seguinte).

**O E2E encontrou um defeito que os testes de cada repositório não viam.** Na primeira execução, MN1 falhou com
10,0 s, 2 ciclos: um ciclo de entrega de estatísticas que acorda antes da recolha não tem nada para enviar, e a
fotografia do *buffer* só viaja com estatísticas (ADR-0010). Corrigido no remote: esse ciclo espera pela
próxima recolha, no máximo um intervalo, e envia-a logo (registado no histórico do ADR-0010).
**1 ciclo** no E2E são 6 s: o intervalo (5 s) mais a amostragem do CPU (1 s,
`internal/collect/machinestatus.go`). O limite de 7 s junta 1 s para a observação pelo condutor.

Higiene: `ErrorLogCollector` removido (−408 linhas; lint do remote 21 → 20); `protectedRoutes` com o teste;
módulo do SDK renomeado; `scripts/go-work.sh`; READMEs sem referências partidas. Lint do central: 54, igual.

## Histórico
* **2026-11-21 —** o SDK foi publicado como `v0.1.0` e o hello-world passou a depender dessa versão, sem
  `replace` (ponto 3 da decisão). Motivo: o CI do hello-world clonava o `main` do SDK para o `replace`, e uma
  mudança nos dois repositórios ao mesmo tempo (o nome do módulo) falhou o `go mod tidy -diff` até o PR do SDK
  entrar. O SDK deixa de ser repositório irmão no CI e no E2E; o `monitor-remote` continua (esquema do *buffer*).
