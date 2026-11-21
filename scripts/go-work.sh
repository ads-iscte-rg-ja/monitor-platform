#!/usr/bin/env bash
# Cria um go.work na pasta que contém os repositórios do Monitor (ADR-0012), para
# desenvolver vários módulos ao mesmo tempo: uma alteração no SDK ou no monitor-api
# passa a ser vista pelos outros sem replace nem tag.
#
# Uso: monitor-platform/scripts/go-work.sh   (de qualquer pasta)
#
# Só para desenvolvimento local: a pasta-mãe não é um repositório, e o CI e os
# Dockerfiles compilam cada repositório sozinho (GOWORK=off). Para o ignorar num
# comando: GOWORK=off go test ./...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

modules=()
for repo in monitor-api monitor-central monitor-remote monitor-go-sdk monitor-hello-world; do
  if [[ -f "$repo/go.mod" ]]; then
    modules+=("./$repo")
  else
    echo "aviso: $repo não existe em $ROOT; fica de fora" >&2
  fi
done

rm -f go.work go.work.sum
go work init "${modules[@]}"
echo "criado $ROOT/go.work com: ${modules[*]}"
