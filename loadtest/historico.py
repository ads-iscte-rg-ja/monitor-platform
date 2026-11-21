#!/usr/bin/env python3
"""Gera o histórico sintético de SC4 (D9): N dias de estatísticas e logs dos hosts de carga.

Os hosts têm de existir (provisionar.py). O ritmo é o do k6 (ingestao.js) e o perfil de cada host
vem do índice no nome, como em provisionar.py: estatísticas a cada 30 s em todos os hosts; erros a
1/s nos ruidosos, a cada 6 s nos normais e nos de rajada (sem rajada) e a cada 120 s nos
silenciosos. Com 1.000 hosts e 31 dias: 89 M estatísticas e 239 M erros.

Cada registo tem o recibo de deduplicação que a ingestão grava (telemetry_receipts), com
source_id 1, 2, 3, ... por host e tipo; o k6 começa noutra gama (PRIMEIRO_SOURCE_ID) para não colidir.
As linhas são inseridas por ordem do tempo, todos os hosts misturados, como chegam na realidade:
inserir host a host deixaria as linhas de cada host juntas no disco e as consultas mais rápidas do
que serão.

A geração divide o período em blocos de horas e corre-os em paralelo, cada um numa ligação psql
(docker compose exec). Não é idempotente: corre uma vez, numa base de dados acabada de criar.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Passo entre erros de cada perfil, em segundos (1 / taxa do k6: ruidoso 1/s, normal 10/min,
# silencioso 0,5/min). O resto da divisão do índice por 100 dá o perfil, como em provisionar.py.
PASSO_ERROS = """CASE WHEN split_part(name,'-',2)::int % 100 BETWEEN 1 AND 4 THEN 1
                      WHEN split_part(name,'-',2)::int % 100 <= 29 THEN 6 ELSE 120 END"""

# :t0 é o instante do primeiro registo (época, s); :a e :b o bloco [a, b). O registo n de um host
# tem o instante t0 + (n-1)*passo, por isso o source_id não depende da ordem dos blocos.
BLOCO = f"""
\\set ON_ERROR_STOP on
SET synchronous_commit = off;
BEGIN;
WITH novos AS (
  INSERT INTO machine_stats(host_id,source_id,cpu_percent,ram_used_mb,ram_total_mb,disk_used_gb,disk_total_gb,collected_at)
  SELECT h.id, n, 5 + random()*60, 2048, 8192, 40, 100, to_timestamp(:t0 + (n-1)*30)
  FROM hosts h CROSS JOIN LATERAL generate_series(ceil((:a - :t0)/30.0)::bigint + 1, ceil((:b - :t0)/30.0)::bigint) n
  WHERE h.hostname LIKE '%.carga.local'
  ORDER BY 8
  RETURNING id, host_id, source_id)
INSERT INTO telemetry_receipts(host_id,kind,source_id,record_id) SELECT host_id,'stat',source_id,id FROM novos;
WITH p AS (SELECT id, {PASSO_ERROS} AS passo FROM hosts WHERE hostname LIKE '%.carga.local'),
novos AS (
  INSERT INTO error_logs(host_id,source_id,app_name,environment,level,message,metadata,created_at)
  SELECT p.id, n, 'app-carga', 'carga', (ARRAY['INFO','WARN','ERROR','CRITICAL'])[n % 4 + 1],
         'falha simulada ' || n || ': timeout ao contactar o serviço de pagamentos',
         '{{"rota":"/encomendas","tentativa":1}}'::jsonb, to_timestamp(:t0 + (n-1)*p.passo)
  FROM p CROSS JOIN LATERAL generate_series(ceil((:a - :t0)::numeric/p.passo)::bigint + 1,
                                            ceil((:b - :t0)::numeric/p.passo)::bigint) n
  ORDER BY 8
  RETURNING id, host_id, source_id)
INSERT INTO telemetry_receipts(host_id,kind,source_id,record_id) SELECT host_id,'error',source_id,id FROM novos;
COMMIT;
"""


def psql(compose: list[str], sql: str, variaveis: dict[str, int] | None = None) -> str:
    cmd = [*compose, "exec", "-T", "postgres", "psql", "-qtA", "-U", "monitor", "-d", "monitor"]
    for nome, valor in (variaveis or {}).items():
        cmd += ["-v", f"{nome}={valor}"]
    r = subprocess.run(cmd, input=sql, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql falhou ({variaveis}): {r.stderr.strip()}")
    return r.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=31)
    ap.add_argument("--horas-por-bloco", type=int, default=6)
    ap.add_argument("--paralelo", type=int, default=8)
    ap.add_argument("--compose", default="docker compose -f compose.yaml",
                    help="comando do Compose (com os -f), separado por espaços")
    args = ap.parse_args()
    compose = args.compose.split()

    # O histórico acaba um minuto antes de agora: collected_at/created_at têm CHECK <= agora.
    fim = int(time.time()) - 60
    t0 = fim - args.dias * 86400
    passo = args.horas_por_bloco * 3600
    blocos = [(a, min(a + passo, fim)) for a in range(t0, fim, passo)]

    # Só para a carga em massa; repõe-se no fim, para a medição correr com a configuração por omissão.
    psql(compose, "ALTER SYSTEM SET max_wal_size = '32GB'; SELECT pg_reload_conf();")
    inicio = time.time()
    with ThreadPoolExecutor(args.paralelo) as ex:
        futuros = {ex.submit(psql, compose, BLOCO, {"t0": t0, "a": a, "b": b}): (a, b) for a, b in blocos}
        for feitos, f in enumerate(as_completed(futuros), 1):
            f.result()
            print(f"  bloco {feitos}/{len(blocos)} ({time.time() - inicio:.0f} s)", file=sys.stderr, flush=True)
    psql(compose, "ALTER SYSTEM RESET max_wal_size; SELECT pg_reload_conf();")
    # O autovacuum teria marcado as páginas antigas como visíveis e recolhido estatísticas; sem isto,
    # o planeador e os index-only scans veriam um estado que um sistema real não tem.
    print("  VACUUM ANALYZE ...", file=sys.stderr, flush=True)
    psql(compose, "VACUUM (ANALYZE) machine_stats; VACUUM (ANALYZE) error_logs; VACUUM (ANALYZE) telemetry_receipts;")
    print(psql(compose, """SELECT format('estatísticas=%s erros=%s recibos=%s tamanho=%s',
      (SELECT COUNT(*) FROM machine_stats), (SELECT COUNT(*) FROM error_logs),
      (SELECT COUNT(*) FROM telemetry_receipts), pg_size_pretty(pg_database_size('monitor')))"""))
    print(f"  gerado em {time.time() - inicio:.0f} s", file=sys.stderr)


if __name__ == "__main__":
    main()
