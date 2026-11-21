#!/usr/bin/env bash
# Corre os testes de carga de uma iteração e gera as tabelas do relatório (D10).
#
# Uso:  loadtest/correr.sh <iteração> [medições...]
#       loadtest/correr.sh baseline                  # todas as medições (~55 min)
#       HOSTS=50 DURACAO=2m loadtest/correr.sh ensaio nominal   # ensaio rápido
#
# Medições: nominal, nominal-x2, nominal-x5 (sensibilidade), noisy-neighbour, recovery-storm e
# capacidade-1, capacidade-2, capacidade-3 (SC3: a mesma carga com 1, 2 e 3 instâncias do central
# atrás do nginx; não fazem parte do conjunto por omissão) e dashboard-30d (SC4: a carga nominal e as
# consultas do dashboard sobre 31 dias de histórico, em duas fases: sem retenção e depois com a
# retenção a 30 dias a correr a cada minuto (dashboard-30d.json e dashboard-30d-retencao.json);
# a geração do histórico, ~330 M registos, demora e precisa de ~150 GB de disco; também fora do conjunto
# por omissão).
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
  local dias=0 primeiro_source=1
  case "$nome" in
    dashboard-30d) dias=${DIAS_HISTORICO:-31}; primeiro_source=1000000000 ;;
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
  if [ "$dias" -gt 0 ]; then
    gerar_historico "$dias"
  fi
  dc up -d --build --wait --scale backend="$instancias" backend nginx prometheus >/dev/null
  dc run --rm --no-deps backend /app/bin/seed >/dev/null
  if [ "$dias" -eq 0 ]; then
    python3 provisionar.py --hosts "$HOSTS" --segredo "$SEGREDO" | psql_carga >/dev/null
  fi
  local primeiro_host
  primeiro_host=$(psql_carga -c "SELECT MIN(id) FROM hosts WHERE hostname LIKE '%.carga.local'")

  correr_k6 "$nome" "$primeiro_source"
  if [ "$dias" -gt 0 ]; then
    # SC4, segunda fase sobre o mesmo histórico: a mesma carga com a retenção ligada. A diferença
    # para a primeira fase é o efeito da retenção na ingestão e nas consultas.
    ligar_retencao
    dc up -d --wait --force-recreate --no-deps backend >/dev/null
    sleep 15 # o Prometheus descobre a instância nova
    # Outra gama de source_id: os da primeira fase seriam deduplicados, não inseridos.
    correr_k6 "$nome-retencao" $(( primeiro_source * 2 ))
  fi
  dc down -v --remove-orphans >/dev/null
}

# Uma corrida do k6 e a recolha dos resultados (usa as variáveis locais de medir).
correr_k6() {
  local nome=$1 primeiro_source=$2
  estado_bd "$nome" antes
  local inicio fim
  inicio=$(date +%s)
  # CPU de cada contentor (o do PostgreSQL não está no Prometheus), a cada ~2 s.
  ( while :; do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' | sed "s/^/$(date +%s) /"; done ) \
    > "results/$nome.cpu.txt" 2>/dev/null &
  local amostrador=$!
  # Os thresholds que falham dão exit 99: é um resultado, não um erro do script.
  dc run --rm --user "$(id -u):$(id -g)" -e CENARIO="$cenario" -e MULT_LOGS="$mult" -e DURACAO="$duracao" -e RESULTADO="$nome" \
     -e ADMIN_EMAIL=admin@carga.local -e ADMIN_PASSWORD="$ADMIN_PASSWORD" -e CENTRAL_GRPC="$grpc" -e CENTRAL_HTTP="$web" \
     -e PRIMEIRO_SOURCE_ID="$primeiro_source" -e PRIMEIRO_HOST_ID="$primeiro_host" \
     k6 run --quiet /scripts/ingestao.js || [ $? -eq 99 ]
  fim=$(date +%s)
  kill "$amostrador" 2>/dev/null || true
  sleep 10 # última recolha do Prometheus
  estado_bd "$nome" depois

  # As contagens são só dos registos do k6 (source_id na gama dele), não do histórico.
  local k6s="source_id >= $primeiro_source AND source_id < $(( primeiro_source + 1000000000 ))"
  python3 recolher.py --prometheus "http://127.0.0.1:${CARGA_PROMETHEUS_PORT:-19090}" \
    --inicio "$inicio" --fim "$fim" \
    --gravados-stats "$(psql_carga -c "SELECT COUNT(*) FROM machine_stats WHERE $k6s")" \
    --gravados-erros "$(psql_carga -c "SELECT COUNT(*) FROM error_logs WHERE $k6s")" \
    --duplicados "$(psql_carga -c "SELECT (SELECT COUNT(*)-COUNT(DISTINCT (host_id,source_id)) FROM error_logs WHERE $k6s)+(SELECT COUNT(*)-COUNT(DISTINCT (host_id,source_id)) FROM machine_stats WHERE $k6s)")" \
    --k6 "results/$nome.json" --hosts "$HOSTS" --instancias "$instancias" --cpu-contentores "results/$nome.cpu.txt" \
    --estado-bd "results/$nome.bd.txt" --saida "$SAIDA/$nome.json"
}

# SC4: hosts e histórico numa base de dados acabada de criar. O PostgreSQL corre sem os limites da
# medição só durante a geração (seriam horas com 2 vCPU); depois é recriado com eles, no mesmo volume,
# e com a cache fria: o histórico não fica em memória à custa da geração.
gerar_historico() {
  echo "   a gerar $1 dias de histórico de $HOSTS hosts (PostgreSQL sem limites)"
  # Exportadas: qualquer comando do Compose sem elas (o run do migrate, por exemplo) recriaria o
  # PostgreSQL com os limites a meio da geração.
  export CARGA_PG_CPUS CARGA_PG_MEM
  CARGA_PG_CPUS=$(nproc)
  CARGA_PG_MEM=$(( $(free -g | awk '/Mem:/{print $2}') / 2 ))g
  dc up -d --wait postgres >/dev/null
  dc run --rm migrate >/dev/null
  python3 provisionar.py --hosts "$HOSTS" --segredo "$SEGREDO" | psql_carga >/dev/null
  python3 historico.py --dias "$1" --paralelo "$(( $(nproc) / 2 ))"
  dc stop postgres >/dev/null
  unset CARGA_PG_CPUS CARGA_PG_MEM
}

# Retenção a 30 dias, a correr a cada minuto, com o maior lote permitido: a melhor configuração do
# mecanismo atual (o que se mede é se acompanha a ingestão e quanto custa).
ligar_retencao() {
  cat >> .carga.env <<EOF
RETENTION_STATS_DAYS=30
RETENTION_ERRORS_DAYS=30
CLEANUP_INTERVAL=1m
CLEANUP_BATCH_SIZE=${CLEANUP_BATCH_SIZE:-10000}
EOF
}

# Tamanho das tabelas e registos já fora da janela de retenção (SC4), antes e depois da medição.
estado_bd() {
  psql_carga -c "SELECT '$2', (SELECT COUNT(*) FROM machine_stats WHERE collected_at < now() - interval '30 days'),
    (SELECT COUNT(*) FROM error_logs WHERE created_at < now() - interval '30 days'),
    pg_total_relation_size('machine_stats'), pg_total_relation_size('error_logs'),
    pg_total_relation_size('telemetry_receipts'), pg_database_size('monitor'), extract(epoch FROM now())::bigint" \
    >> "results/$1.bd.txt"
}

rm -f results/*.bd.txt
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
