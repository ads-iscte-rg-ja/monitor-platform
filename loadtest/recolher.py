#!/usr/bin/env python3
"""Junta numa medição os resultados do k6 (lado do agente), do Prometheus (lado do servidor,
ADR-0004) e da base de dados (integridade: o que foi confirmado ficou gravado, sem duplicados)."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

CPUS = 2  # limite do contentor do central (loadtest/compose.yaml)


def consultar(prometheus: str, expressao: str, quando: int) -> list[dict]:
    url = f"{prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": expressao, "time": quando})
    with urllib.request.urlopen(url, timeout=30) as resposta:
        corpo = json.load(resposta)
    if corpo.get("status") != "success":
        raise SystemExit(f"Prometheus: {expressao}: {corpo}")
    return corpo["data"]["result"]


def escalar(prometheus: str, expressao: str, quando: int) -> float | None:
    resultado = consultar(prometheus, expressao, quando)
    if not resultado:
        return None
    valor = float(resultado[0]["value"][1])
    return None if valor != valor else valor  # NaN: sem amostras


def dashboard_durante(prometheus: str, inicio: int, duracao_s: float | None) -> float | None:
    """p95 do dashboard só enquanto houve hosts a enviar o backlog (recovery-storm)."""
    if not duracao_s:
        return None
    janela = max(int(duracao_s) + 10, 30)
    return ms(escalar(prometheus, 'histogram_quantile(0.95, sum by (le) (increase(monitor_http_request_duration_seconds_bucket'
                      f'{{route="/api/v1/dashboard/summary"}}[{janela}s])))', inicio + janela))


def servidor(prometheus: str, inicio: int, fim: int) -> dict:
    d = f"{max(fim - inicio, 30)}s"
    q = lambda e: escalar(prometheus, e, fim)  # noqa: E731
    por_codigo = {
        r["metric"].get("code", "?"): float(r["value"][1])
        for r in consultar(prometheus, f"sum by (code) (increase(monitor_ingest_request_duration_seconds_count[{d}]))", fim)
    }
    registos = {
        f'{r["metric"]["kind"]}_{r["metric"]["outcome"]}': float(r["value"][1])
        for r in consultar(prometheus, f"sum by (kind, outcome) (increase(monitor_ingest_records_total[{d}]))", fim)
    }
    return {
        "ingestao_p95_ms": ms(q(f"histogram_quantile(0.95, sum by (le) (increase(monitor_ingest_request_duration_seconds_bucket[{d}])))")),
        "ingestao_p99_ms": ms(q(f"histogram_quantile(0.99, sum by (le) (increase(monitor_ingest_request_duration_seconds_bucket[{d}])))")),
        "pedidos_por_codigo": por_codigo,
        "registos": registos,
        "dashboard_p95_ms": ms(q(f'histogram_quantile(0.95, sum by (le) (increase(monitor_http_request_duration_seconds_bucket{{route="/api/v1/dashboard/summary"}}[{d}])))')),
        "cpu_media_pct": pct(q(f"increase(process_cpu_seconds_total[{d}]) / {max(fim - inicio, 30)}")),
        "cpu_max_pct": pct(q(f"max_over_time(rate(process_cpu_seconds_total[30s])[{d}:5s])")),
        "memoria_max_mb": mb(q(f"max_over_time(process_resident_memory_bytes[{d}])")),
        "ligacoes_bd_max": q(f"max_over_time(go_sql_in_use_connections[{d}])"),
        "ligacoes_bd_limite": q("go_sql_max_open_connections"),
        "esperas_por_ligacao": q(f"increase(go_sql_wait_count_total[{d}])"),
        "espera_por_ligacao_s": q(f"increase(go_sql_wait_duration_seconds_total[{d}])"),
    }


def ms(segundos: float | None) -> float | None:
    return None if segundos is None else round(segundos * 1000, 1)


def pct(cores: float | None) -> float | None:
    return None if cores is None else round(100 * cores / CPUS, 1)


def mb(octetos: float | None) -> float | None:
    return None if octetos is None else round(octetos / 2**20, 1)


def agente(caminho: Path) -> dict:
    """Extrai do resumo do k6 as métricas e os thresholds de que o relatório precisa."""
    dados = json.loads(caminho.read_text())
    metricas = dados.get("metrics", {})
    resumo = {}
    for nome, m in metricas.items():
        if nome.startswith(("grpc_req_duration", "atraso_central", "tempo_recuperacao", "http_req_duration",
                            "lotes_perdidos", "registos_confirmados", "respostas_nao_ok", "iterations",
                            "backlog_total")):
            resumo[nome] = {k: v for k, v in m.get("values", {}).items()}
            if m.get("thresholds"):
                resumo[nome]["thresholds"] = {t: r.get("ok") for t, r in m["thresholds"].items()}
    resumo["duracao_s"] = round(dados.get("state", {}).get("testRunDurationMs", 0) / 1000, 1)
    return resumo


def valor_recuperacao(agente_resumo: dict) -> float | None:
    m = agente_resumo.get("tempo_recuperacao")
    return None if not m else m.get("max", 0) / 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prometheus", required=True)
    ap.add_argument("--inicio", type=int, required=True)
    ap.add_argument("--fim", type=int, required=True)
    ap.add_argument("--gravados-stats", type=int, required=True)
    ap.add_argument("--gravados-erros", type=int, required=True)
    ap.add_argument("--duplicados", type=int, required=True)
    ap.add_argument("--k6", type=Path, required=True)
    ap.add_argument("--hosts", type=int, required=True)
    ap.add_argument("--saida", type=Path, required=True)
    a = ap.parse_args()
    medicao = {
        "janela": {"inicio": a.inicio, "fim": a.fim},
        "hosts": a.hosts,
        "agente": agente(a.k6),
        "servidor": servidor(a.prometheus, a.inicio, a.fim),
        "dashboard_p95_ms_durante_recuperacao": None,
        "base_de_dados": {"stats": a.gravados_stats, "erros": a.gravados_erros, "duplicados": a.duplicados},
    }
    recuperacao = valor_recuperacao(medicao["agente"])
    medicao["dashboard_p95_ms_durante_recuperacao"] = dashboard_durante(a.prometheus, a.inicio, recuperacao)
    a.saida.write_text(json.dumps(medicao, indent=2, ensure_ascii=False) + "\n")
    print(f"   escrito {a.saida}")


if __name__ == "__main__":
    main()
