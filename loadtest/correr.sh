#!/usr/bin/env bash
# Corre os testes de carga de uma iteração e gera as tabelas do relatório (D10).
#
# Uso:  loadtest/correr.sh <iteração> [medições...]
#       loadtest/correr.sh baseline                  # todas as medições (~55 min)
#       HOSTS=50 DURACAO=2m loadtest/correr.sh ensaio nominal   # ensaio rápido
#
# Medições: nominal, nominal-x2, nominal-x5 (sensibilidade), noisy-neighbour, recovery-storm e
# capacidade-1, capacidade-2, capacidade-3 (SC3: a mesma carga com 1, 2 e 3 instâncias do central
# atrás do nginx; não fazem parte do conjunto por omissão).
# Cada medição recria o ambiente do zero (base de dados vazia, central acabado de arrancar), para
# não herdar dados nem caches da anterior. Os resultados ficam em docs/metrics/<iteração>/carga/.
#
# Requisitos: Docker com Compose, python3, e os repositórios irmãos monitor-central e monitor-api.
set -euo pipefail
cd "$(dirname "$0")"

ITER=${1:?uso: correr.sh <iteração> [medições...]}
shift
if [ $# -gt 0 ]; then MEDICOES=("$@"); else MEDICOES=(nominal nominal-x2 nominal-x5 noisy-neighbour recovery-storm); fi
HOSTS=${HOSTS:-1000}
DURACAO=${DURACAO:-10m}
SAIDA=../docs/metrics/$ITER/carga
mkdir -p results dados "$SAIDA"

dc() { docker compose -f compose.yaml "$@"; }
# Se o script falhar a meio, o ambiente de carga não fica a ocupar portas e CPU.
trap 'dc down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
psql_carga() { dc exec -T postgres psql -qtA -U monitor -d monitor "$@"; }

gerar_env() {
  SEGREDO=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  ADMIN_PASSWORD="Carga-$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')1!"
  cat > .carga.env <<EOF
POSTGRES_USER=monitor
POSTGRES_PASSWORD=carga
POSTGRES_DB=monitor
POSTGRES_SSLMODE=disable
POSTGRES_MAX_OPEN_CONNS=25
POSTGRES_MAX_IDLE_CONNS=5
APP_ENV=development
COOKIE_SECURE=false
LOG_FORMAT=json
LOG_LEVEL=warn
HOST_API_KEY_SECRET=$SEGREDO
ADMIN_EMAIL=admin@carga.local
ADMIN_PASSWORD=$ADMIN_PASSWORD
ADMIN_NAME=Carga
LOGIN_ATTEMPTS_PER_IP=1000
LOGIN_ATTEMPTS_PER_ACCOUNT=1000
SMTP_HOST=127.0.0.1
SMTP_PORT=2525
SMTP_USER=carga
SMTP_PASS=carga
SMTP_FROM=carga@monitor.local
EOF
}

medir() {
  local nome=$1 cenario=$1 mult=1 duracao=$DURACAO instancias=1 grpc=backend:3334 web=http://backend:3333
  case "$nome" in
    capacidade-[1-9]) cenario=capacidade; instancias=${nome#capacidade-}; duracao=${DURACAO_CAPACIDADE:-5m}
      grpc=nginx:3334; web=http://nginx:3333 ;;
    nominal-x2) cenario=nominal; mult=2 ;;
    nominal-x5) cenario=nominal; mult=5 ;;
    noisy-neighbour) duracao=${DURACAO_RAJADA:-8m} ;;
    recovery-storm) duracao=${DURACAO_RECUPERACAO:-16m} ;;
    nominal) ;;
    *) echo "medição desconhecida: $nome" >&2; exit 2 ;;
  esac
  echo "== $nome (cenário $cenario, logs x$mult, $HOSTS hosts, $instancias instância(s))"

  dc down -v --remove-orphans >/dev/null 2>&1 || true
  gerar_env
  dc up -d --build --wait --scale backend="$instancias" backend nginx prometheus >/dev/null
  dc run --rm --no-deps backend /app/bin/seed >/dev/null
  python3 provisionar.py --hosts "$HOSTS" --segredo "$SEGREDO" | psql_carga >/dev/null

  local inicio fim
  inicio=$(date +%s)
  # CPU de cada contentor (o do PostgreSQL não está no Prometheus), a cada ~2 s.
  ( while :; do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' | sed "s/^/$(date +%s) /"; done ) \
    > "results/$nome.cpu.txt" 2>/dev/null &
  local amostrador=$!
  # Os thresholds que falham dão exit 99: é um resultado, não um erro do script.
  dc run --rm --user "$(id -u):$(id -g)" -e CENARIO="$cenario" -e MULT_LOGS="$mult" -e DURACAO="$duracao" -e RESULTADO="$nome" \
     -e ADMIN_EMAIL=admin@carga.local -e ADMIN_PASSWORD="$ADMIN_PASSWORD" -e CENTRAL_GRPC="$grpc" -e CENTRAL_HTTP="$web" \
     k6 run --quiet /scripts/ingestao.js || [ $? -eq 99 ]
  fim=$(date +%s)
  kill "$amostrador" 2>/dev/null || true
  sleep 10 # última recolha do Prometheus

  python3 recolher.py --prometheus "http://127.0.0.1:${CARGA_PROMETHEUS_PORT:-19090}" \
    --inicio "$inicio" --fim "$fim" \
    --gravados-stats "$(psql_carga -c 'SELECT COUNT(*) FROM machine_stats')" \
    --gravados-erros "$(psql_carga -c 'SELECT COUNT(*) FROM error_logs')" \
    --duplicados "$(psql_carga -c "SELECT (SELECT COUNT(*)-COUNT(DISTINCT (host_id,source_id)) FROM error_logs)+(SELECT COUNT(*)-COUNT(DISTINCT (host_id,source_id)) FROM machine_stats)")" \
    --k6 "results/$nome.json" --hosts "$HOSTS" --instancias "$instancias" --cpu-contentores "results/$nome.cpu.txt" \
    --saida "$SAIDA/$nome.json"
  dc down -v --remove-orphans >/dev/null
}

for m in "${MEDICOES[@]}"; do medir "$m"; done

{
  echo "data: $(date -Is)"
  for r in monitor-central monitor-api monitor-platform; do
    echo "$r: $(git -C ../../$r rev-parse --abbrev-ref HEAD)@$(git -C ../../$r rev-parse --short HEAD)$( [ -n "$(git -C ../../$r status --porcelain)" ] && echo ' (com alterações por commitar)')"
  done
  echo "hosts simulados: $HOSTS; duração dos cenários contínuos: $DURACAO"
  echo "limites: central 2 vCPU / 4 GB por instância; PostgreSQL 2 vCPU / 4 GB; nginx e k6 sem limites (loadtest/compose.yaml)"
  echo "k6: $(grep -o 'grafana/k6:[0-9.]*' compose.yaml)"
  echo "cpu: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs) ($(nproc) threads), memória: $(free -g | awk '/Mem:/{print $2}') GB"
} > "$SAIDA/ambiente.txt"

python3 tabelas.py "$ITER"
echo "Resultados em docs/metrics/$ITER/carga/ e tabelas em docs/metrics/$ITER/."
