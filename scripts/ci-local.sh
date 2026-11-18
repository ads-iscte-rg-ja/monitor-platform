#!/usr/bin/env bash
# Corre localmente as mesmas verificações do workflow go-ci.yml.
#
# Uso, a partir da raiz de qualquer repositório Go do Monitor:
#   ../monitor-platform/scripts/ci-local.sh
# Testes de integração (só central): definir MONITOR_TEST_DSN para uma BD isolada.
set -euo pipefail

GOLANGCI_LINT_VERSION=v2.15.0
GOVULNCHECK_VERSION=v1.10.0
PLATFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GOWORK=off CGO_ENABLED=1

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  printf 'Falta %s. Instalar com:\n  go install %s\n' "$1" "$2" >&2
  exit 1
}

[ -f go.mod ] || { echo "Correr na raiz de um módulo Go (go.mod não encontrado)." >&2; exit 1; }
need golangci-lint "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}"
need govulncheck "golang.org/x/vuln/cmd/govulncheck@${GOVULNCHECK_VERSION}"

step "Higiene"
files="$(gofmt -l .)"
if [ -n "$files" ]; then printf 'Ficheiros por formatar:\n%s\n' "$files"; exit 1; fi
go mod tidy -diff
go mod verify

step "Lint (configuração partilhada)"
golangci-lint run --config="${PLATFORM_DIR}/lint/.golangci.yml" --show-stats ./... || lint_failed=1

step "Testes unitários (-race)"
go test -race -count=1 -covermode=atomic -coverprofile=coverage.out ./...
go tool cover -func=coverage.out | tail -1

if [ -d internal/integration ]; then
  step "Testes de integração"
  if [ -n "${MONITOR_TEST_DSN:-}" ]; then
    go test -race -count=1 -tags integration ./internal/integration
  else
    echo "MONITOR_TEST_DSN não definido: integração ignorada."
  fi
fi

step "Vulnerabilidades"
govulncheck ./...

if [ "${lint_failed:-0}" = 1 ]; then
  printf '\nLint com issues (ver acima). Na fase de baseline isto não bloqueia o CI.\n'
  exit 1
fi
printf '\nTudo verde.\n'
