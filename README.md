# monitor-platform

Infraestrutura de qualidade e artefactos **transversais** do sistema Monitor: o CI partilhado pelos
repositórios Go, os testes de sistema, as decisões arquiteturais e o relatório de Arquitetura e
Desenho de Software (ADS). A razão de existir deste repositório está no
[ADR-0002](docs/adr/0002-repositorio-monitor-platform.md).

| Repositório | Papel |
|---|---|
| `monitor-central` | Servidor central: ingestão, dashboard, alertas, PostgreSQL |
| `monitor-remote` | Agente em cada host: recolha e entrega com buffer SQLite |
| `monitor-go-sdk` | Biblioteca para as aplicações escreverem logs no buffer |
| `monitor-hello-world` | Aplicação de exemplo que usa o SDK |
| **`monitor-platform`** | **Este repositório** |

## Estrutura

```
.github/workflows/
  go-ci.yml          workflow reutilizável: higiene, lint, testes, integração, govulncheck, SonarQube Cloud
  self-check.yml     CI deste repositório: actionlint, validação do lint, compilação do relatório
lint/.golangci.yml   configuração única do golangci-lint (inclui as regras de camadas de todo o sistema)
scripts/ci-local.sh  as mesmas verificações do CI, para correr localmente
scripts/medir.py     mede os 4 repositórios e gera as tabelas do relatório (docs/metrics/)
templates/           ficheiros a copiar para cada repositório (ci.yml, dependabot.yml, sonar-project.properties)
e2e/                 testes ponta a ponta com os 4 componentes (Docker Compose)
loadtest/            testes de carga k6 e geração das tabelas do relatório
tools/codemetrics/   acoplamento entre pacotes (Martin) e complexidade por função
docs/
  PLANO_MELHORIAS.md plano de melhoria arquitetural (requisitos, métricas, decisões, roadmap)
  adr/               registo de decisões arquiteturais
  metrics/           resultados das medições por iteração
report/              relatório de ADS em LaTeX
```

## Usar o CI num repositório

1. Copiar `templates/ci.yml` para `.github/workflows/ci.yml` (no `monitor-central`, manter `integration-packages`; nos outros, apagar).
2. Copiar `templates/dependabot.yml` para `.github/dependabot.yml`.
3. Copiar `templates/sonar-project.properties` para a raiz e preencher a organização e a chave do projeto.
4. Adicionar o secret `SONAR_TOKEN` ao repositório.

O workflow é chamado com `@v1`. Para publicar uma alteração ao pipeline, faz-se merge aqui e move-se a tag:
`git tag -f v1 && git push -f origin v1`.

> Os repositórios de outro dono só podem chamar o workflow reutilizável se este repositório for **público**.

## Correr localmente

Com os repositórios lado a lado (como em `monitor-ws/`), na raiz de qualquer repositório Go:

```sh
../monitor-platform/scripts/ci-local.sh
# testes de integração do central:
MONITOR_TEST_DSN='postgres://…' ../monitor-platform/scripts/ci-local.sh
```

Ferramentas, com as mesmas versões do CI:

```sh
go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.15.0
go install golang.org/x/vuln/cmd/govulncheck@v1.10.0
```

## Medir

```sh
scripts/medir.py baseline     # ou iter-N; detalhes em docs/metrics/README.md
```

## Relatório

```sh
cd report && make            # main.pdf
make dados ITER=baseline     # copia as tabelas geradas pelas medições
```
