# ADR-0002: Repositório `monitor-platform` para CI partilhado e artefactos transversais

* **Estado:** Aceite
* **Data:** 2026-11-18
* **QA principal:** Modifiability (da infraestrutura de qualidade)
* **Cenários relacionados:** TE1, MO2

## Contexto
O sistema está dividido em 4 repositórios Go (`monitor-central`, `monitor-remote`, `monitor-go-sdk`,
`monitor-hello-world`) que precisam das **mesmas** verificações de qualidade: formatação, lint com os
mesmos limites, testes com `-race`, vulnerabilidades e SonarQube Cloud. Há também artefactos que não
pertencem a nenhum repositório, porque dizem respeito ao **sistema inteiro**: testes E2E, testes de carga,
regras de dependência entre camadas, ADRs e o relatório de ADS.

Na baseline (2026-11-18) não havia CI, e os testes de integração do central estiveram partidos sem
ninguém dar por isso. Os artefactos transversais estavam previstos em `monitor-ws/`, que não é um
repositório git, por isso perder-se-iam.

## Decisão
Criar o repositório `monitor-platform` com:
* `.github/workflows/go-ci.yml`: **workflow reutilizável** (`workflow_call`) com todo o pipeline. Cada repo
  tem só um `ci.yml` de ~20 linhas que o chama com `@v1`;
* `lint/.golangci.yml`: configuração **única** de lint, incluindo as regras `depguard` das camadas de todos os repos;
* `scripts/ci-local.sh`: as mesmas verificações, para correr localmente;
* `templates/`: o que o GitHub obriga a ter em cada repo (`ci.yml`, `dependabot.yml`, `sonar-project.properties`);
* `e2e/`, `loadtest/`, `tools/`: testes e ferramentas do sistema inteiro;
* `docs/`: plano, ADRs e medições; `report/`: relatório de ADS em LaTeX.

Os repositórios consomem uma **versão** do pipeline (tag `v1`, movida deliberadamente) e não o `main`.

## Fundamentação teórica
* **Abstract Common Services** (modifiability): o que é comum aos 4 repos fica num só sítio.
* **Increase Cohesion**: CI, testes de sistema e documentação de arquitetura mudam pelas mesmas razões.
* **Restrict Dependencies** + versionamento: os repos dependem de uma interface versionada (`@v1`), por isso
  uma alteração no CI não parte os 4 pipelines ao mesmo tempo.
* **Implementation structure** (allocation view, slide 02): mapeamento explícito dos elementos para repositórios.
* As regras `depguard` tornam a tática **Restrict Dependencies** executável. É uma verificação automática
  de que *"an implementation conforms to the specified architecture"* (slide 02).

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Copiar o pipeline para os 4 repos | 4 cópias divergem; cada mudança tem de ser feita 4 vezes (o mesmo problema que D12 resolve no código) |
| Workflow reutilizável dentro do `monitor-central` | O CI e os testes de sistema não pertencem ao central; acoplaria a infraestrutura de todos a um componente |
| **Monorepo** com os 4 repos | Elimina a duplicação de raiz e permite mudanças atómicas ao contrato, mas perde a separação deliberada de módulos (`GOWORK=off` no central, ciclo de vida próprio do SDK), obriga a reescrever o histórico a 3 semanas do prazo e coincide com o trabalho de EUVI no mesmo código. Fica como evolução possível |
| Composite action para o setup do Go | Os passos de setup são 2 linhas; a action acrescentava mais uma referência versionada a manter (YAGNI) |

## Consequências
* **Positivas:** uma alteração ao CI faz-se 1 vez; os limites de qualidade são iguais em todo o lado; a
  arquitetura de módulos fica escrita como regras verificáveis; o professor tem um repositório com a arquitetura,
  as decisões, a infraestrutura de qualidade e o relatório.
* **Negativas / trade-offs:**
  * testar uma alteração ao CI exige um PR aqui e mover a tag;
  * o `monitor-platform` conhece os caminhos internos dos outros repos (regras `depguard`), por isso mover um
    pacote exige também um PR aqui. Aceite: essas mudanças são **arquiteturais** e devem ser revistas como tal;
  * o pipeline faz *checkout* de outros repositórios (a configuração de lint do `monitor-platform` e, no SDK
    e no hello-world, o esquema do `monitor-remote`). O `GITHUB_TOKEN` de cada job só dá acesso ao próprio
    repositório, mesmo dentro da organização, por isso estes repositórios têm de ser **públicos** (ou seria
    preciso uma GitHub App). Isto é coerente com a decisão de tornar todos os repos públicos.

## Verificação
* Os 4 repositórios correm o pipeline através de `go-ci.yml@v1` (TE1).
* `golangci-lint config verify` e `actionlint` passam no CI do próprio `monitor-platform` (`self-check.yml`).
* Validação local a 2026-11-18: a configuração deteta a violação real `handlers → database`
  (`monitor-central/internal/handlers/health.go:8`) e não dá falsos positivos entre repos.
