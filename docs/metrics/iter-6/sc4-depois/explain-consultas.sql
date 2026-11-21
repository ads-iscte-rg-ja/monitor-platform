# Resultados (EXPLAIN ANALYZE, 21/11/2026), mesmos dados e limites que iter-6/sc4-antes/explain.txt
#
# Antes da migração 8 (consultas novas, índices antigos):
#   CPU médio do último registo (lateral)          55 000 ms -> 19 ms
#   Nomes de aplicação (loose index scan)          17 146 ms -> 0,6 ms
#   Contagem com teto: sem filtro / host / nível   13 340 / 1 279 / — ms -> 2,1 / 7,8 / 10,2 ms
#   Consulta constante, parâmetros ligados (\bind): contagem sem filtro 1,7 ms; host 2,0 ms;
#     lista host 0,5 ms; lista sem filtro 0,4 ms (os filtros vazios dobram-se e os índices aplicam-se)
# Depois da migração 8, com a cache fria (PostgreSQL reiniciado):
#   Métricas de 1 mês (índice de cobertura)        5 314 ms -> 265 ms (host 191), 255 ms (host 517)
#   Erros de hoje (error_counts_hourly)            966 ms -> 121 ms
#   CPU médio do último registo                    179 ms (index-only scan)
# Consultas novas (ADR-0017) sobre os 31 dias de iter-6/sc4-antes, PostgreSQL 2 vCPU / 4 GB

## explain-novas
SET statement_timeout='180s';
\echo == AvgLateral
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COALESCE(AVG(latest.cpu_percent),0) FROM hosts h CROSS JOIN LATERAL (SELECT cpu_percent FROM machine_stats WHERE host_id=h.id ORDER BY collected_at DESC LIMIT 1) latest;
\echo == AppNamesRecursive
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) WITH RECURSIVE apps(name) AS ((SELECT app_name FROM error_logs ORDER BY app_name LIMIT 1) UNION ALL SELECT (SELECT e.app_name FROM error_logs e WHERE e.app_name > apps.name ORDER BY e.app_name LIMIT 1) FROM apps WHERE apps.name IS NOT NULL) SELECT name FROM apps WHERE name IS NOT NULL ORDER BY name;
\echo == CountCapped
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COUNT(*) FROM (SELECT 1 FROM error_logs el WHERE 1=1 LIMIT 10001) t;
\echo == CountCappedHost
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COUNT(*) FROM (SELECT 1 FROM error_logs el WHERE 1=1 AND el.host_id=2 LIMIT 10001) t;
\echo == CountCappedLevel
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COUNT(*) FROM (SELECT 1 FROM error_logs el WHERE 1=1 AND el.level='CRITICAL' LIMIT 10001) t;

## explain-const
SET statement_timeout='120s';
\echo == count sem filtros
EXPLAIN (ANALYZE, COSTS OFF) SELECT COUNT(*) FROM (SELECT 1 FROM error_logs el WHERE ($1::bigint = 0 OR el.host_id = $1) AND ($2::text = '' OR el.level = $2) AND ($3::text = '' OR el.app_name = $3) AND ($4::text = '' OR el.message ILIKE $4) LIMIT $5) AS capped \bind 0 '' '' '' 10001 \g
\echo == count host
EXPLAIN (ANALYZE, COSTS OFF) SELECT COUNT(*) FROM (SELECT 1 FROM error_logs el WHERE ($1::bigint = 0 OR el.host_id = $1) AND ($2::text = '' OR el.level = $2) AND ($3::text = '' OR el.app_name = $3) AND ($4::text = '' OR el.message ILIKE $4) LIMIT $5) AS capped \bind 2 '' '' '' 10001 \g
\echo == list host page 1
EXPLAIN (ANALYZE, COSTS OFF) SELECT el.id FROM error_logs el JOIN hosts h ON h.id = el.host_id WHERE ($1::bigint = 0 OR el.host_id = $1) AND ($2::text = '' OR el.level = $2) AND ($3::text = '' OR el.app_name = $3) AND ($4::text = '' OR el.message ILIKE $4) ORDER BY el.created_at DESC, el.id DESC LIMIT $5 OFFSET $6 \bind 2 '' '' '' 20 0 \g
\echo == list sem filtros page 1
EXPLAIN (ANALYZE, COSTS OFF) SELECT el.id FROM error_logs el JOIN hosts h ON h.id = el.host_id WHERE ($1::bigint = 0 OR el.host_id = $1) AND ($2::text = '' OR el.level = $2) AND ($3::text = '' OR el.app_name = $3) AND ($4::text = '' OR el.message ILIKE $4) ORDER BY el.created_at DESC, el.id DESC LIMIT $5 OFFSET $6 \bind 0 '' '' '' 20 0 \g

## explain-mig
\echo == Metrics1m (host 191)
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT AVG(cpu_percent), AVG(ram_used_mb), MAX(ram_total_mb), AVG(disk_used_gb), MAX(disk_total_gb), date_bin('1 day', collected_at, TIMESTAMPTZ '2000-01-01') b FROM machine_stats WHERE host_id=191 AND collected_at >= NOW()-INTERVAL '30 days' AND collected_at<=NOW() GROUP BY b ORDER BY b;
\echo == Metrics1m (host 517, outro)
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT AVG(cpu_percent), AVG(ram_used_mb), MAX(ram_total_mb), AVG(disk_used_gb), MAX(disk_total_gb), date_bin('1 day', collected_at, TIMESTAMPTZ '2000-01-01') b FROM machine_stats WHERE host_id=517 AND collected_at >= NOW()-INTERVAL '30 days' AND collected_at<=NOW() GROUP BY b ORDER BY b;
\echo == CountErrorsToday (contadores)
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COALESCE(SUM(count),0), COALESCE(SUM(count) FILTER (WHERE level IN ('CRITICAL','PANIC')),0) FROM error_counts_hourly WHERE bucket >= CURRENT_DATE AND bucket < CURRENT_DATE + INTERVAL '1 day';
\echo == AvgLateral (índice de cobertura)
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT COALESCE(AVG(latest.cpu_percent),0) FROM hosts h CROSS JOIN LATERAL (SELECT cpu_percent FROM machine_stats WHERE host_id=h.id ORDER BY collected_at DESC LIMIT 1) latest;
