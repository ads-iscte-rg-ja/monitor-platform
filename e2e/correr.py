#!/usr/bin/env python3
"""Testes ponta a ponta do Monitor (ADR-0012): caminho feliz, AV1, MN1 e SE1.

Constrói o sistema a partir dos repositórios irmãos (compose.yaml), provisiona os hosts,
gera logs com o hello-world (SDK), provoca as falhas e verifica o estado nos dois lados:
PostgreSQL do central e buffer SQLite do remote. Nunca conclui a partir de mensagens de log,
exceto para saber que o remote pausou (SE1), que é o comportamento a provar.

Uso (a partir de qualquer pasta, com Docker e openssl):
    monitor-platform/e2e/correr.py                 # todos os cenários, paragem de 60 s
    monitor-platform/e2e/correr.py --paragem 3600  # AV1 com o central em baixo 1 h
    monitor-platform/e2e/correr.py --manter        # deixa o Compose de pé no fim

Escreve e2e/resultados/<data>.json (e os logs dos serviços, se algum cenário falhar) e sai
com código 1 se algum cenário falhar e 2 se o sistema não arrancar.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
ESTADO = AQUI / ".estado"
RESULTADOS = AQUI / "resultados"
COMPOSE = ["docker", "compose", "-f", str(AQUI / "compose.yaml")]
# Como em monitor-central/internal/utils/apikey e em loadtest/provisionar.py.
PREFIXO_DIGEST = b"monitor:host-api-key:v1:"
NIVEIS = 5  # o hello-world escreve 1 log de cada nível por cópia (INFO … PANIC)
# Intervalos do remote no compose.yaml.
INTERVALO_ESTATISTICAS = 5.0
# Um ciclo de recolha dura o intervalo mais a amostragem do CPU (1 s, monitor-remote
# internal/collect/machinestatus.go); a estatística seguinte, com a fotografia, sai logo a seguir.
AMOSTRAGEM_CPU = 1.0
MARGEM_OBSERVACAO = 1.0  # o condutor observa os dois lados a cada 0,25 s, mais o custo do docker exec
REPOSITORIOS = ["monitor-api", "monitor-central", "monitor-remote", "monitor-go-sdk", "monitor-hello-world", "monitor-platform"]


class Falha(Exception):
    """Uma condição esperada não aconteceu dentro do prazo."""


@dataclass
class Chaves:
    segredo: str
    principal: str
    revogada: str
    substituta: str
    invalida: str
    admin: str

    def digest(self, chave: str) -> str:
        return hmac.new(bytes.fromhex(self.segredo), PREFIXO_DIGEST + chave.encode(), hashlib.sha256).hexdigest()


@dataclass
class Cenario:
    id: str
    descricao: str
    passa: bool = False
    medido: dict = field(default_factory=dict)
    limite: str = ""
    erro: str | None = None


# --------------------------------------------------------------------------- Docker

def compose(*args: str, chave_intruso: str = "", verificar: bool = True, entrada: str | None = None) -> str:
    env = os.environ | {"E2E_CHAVE_PRINCIPAL": CHAVES.principal, "E2E_CHAVE_INTRUSO": chave_intruso}
    proc = subprocess.run([*COMPOSE, *args], env=env, input=entrada, capture_output=True, text=True)
    if verificar and proc.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} falhou ({proc.returncode}):\n{proc.stderr[-4000:]}")
    return proc.stdout


def psql(sql: str) -> list[list[str]]:
    out = compose("exec", "-T", "postgres", "psql", "-U", "monitor", "-d", "monitor", "-At", "-F", "|",
                  "-v", "ON_ERROR_STOP=1", "-c", sql)
    return [linha.split("|") for linha in out.splitlines() if linha]


def sqlite(servico: str, sql: str, *, a_correr: bool = True) -> list[list[str]]:
    """Consulta o buffer: docker exec se o agente está a correr; senão um contentor descartável."""
    if a_correr:
        args = ["exec", "-T", servico, "sqlite3", "-separator", "|", "/data/buffer.db", sql]
    else:
        args = ["run", "--rm", "--no-deps", "-T", "--entrypoint", "sqlite3", servico, "-separator", "|",
                "/data/buffer.db", sql]
    return [linha.split("|") for linha in compose(*args).splitlines() if linha]


def esperar(condicao, prazo: float, descricao: str, intervalo: float = 0.25) -> float:
    """Espera que condicao() seja verdadeira; devolve o tempo que demorou. Nunca dorme às cegas."""
    inicio = time.monotonic()
    ultimo_erro = None
    while time.monotonic() - inicio < prazo:
        try:
            if condicao():
                return time.monotonic() - inicio
        except RuntimeError as erro:  # serviço ainda a arrancar
            ultimo_erro = erro
        time.sleep(intervalo)
    raise Falha(f"{descricao}: não aconteceu em {prazo:.0f} s" + (f" (último erro: {ultimo_erro})" if ultimo_erro else ""))


def gerar_logs(servico: str, n: int) -> None:
    if n % NIVEIS:
        raise ValueError(f"n tem de ser múltiplo de {NIVEIS}")
    compose("run", "--rm", "--no-deps", servico, "-count", str(n // NIVEIS))


# --------------------------------------------------------------------------- estado

def buffer(servico: str, *, a_correr: bool = True) -> dict[str, int]:
    linha = sqlite(servico, """SELECT
 (SELECT COUNT(*) FROM error_logs),
 (SELECT COUNT(*) FROM machine_stats),
 (SELECT COUNT(*) FROM delivery_status WHERE record_type='error_log' AND sent_at IS NULL AND quarantine_reason IS NULL),
 (SELECT COUNT(*) FROM delivery_status WHERE record_type='machine_stat' AND sent_at IS NULL AND quarantine_reason IS NULL),
 (SELECT COUNT(*) FROM delivery_status WHERE quarantine_reason IS NOT NULL),
 (SELECT COUNT(*) FROM delivery_status WHERE record_type='error_log' AND sent_at IS NOT NULL),
 (SELECT COUNT(*) FROM delivery_status WHERE record_type='machine_stat' AND sent_at IS NOT NULL)""", a_correr=a_correr)[0]
    chaves = ["logs", "estatisticas", "logs_pendentes", "estatisticas_pendentes", "quarentena", "logs_enviados",
              "estatisticas_enviadas"]
    return dict(zip(chaves, map(int, linha)))


def central(host_id: int) -> dict[str, int]:
    linha = psql(f"""SELECT
 (SELECT COUNT(*) FROM error_logs WHERE host_id={host_id}),
 (SELECT COUNT(*) FROM machine_stats WHERE host_id={host_id}),
 (SELECT COALESCE(MAX(quarantined), 0) FROM host_buffer_status WHERE host_id={host_id})""")[0]
    return dict(zip(["logs", "estatisticas", "quarentena"], map(int, linha)))


def ids_entregues(servico: str) -> dict[str, set[int]]:
    ids: dict[str, set[int]] = {"error_log": set(), "machine_stat": set()}
    for tipo, record_id in sqlite(servico, "SELECT record_type, record_id FROM delivery_status WHERE sent_at IS NOT NULL",
                                  a_correr=False):
        ids[tipo].add(int(record_id))
    return ids


def ids_no_buffer(servico: str) -> dict[str, set[int]]:
    return {
        "error_log": {int(r[0]) for r in sqlite(servico, "SELECT id FROM error_logs", a_correr=False)},
        "machine_stat": {int(r[0]) for r in sqlite(servico, "SELECT id FROM machine_stats", a_correr=False)},
    }


def ids_no_central(host_id: int) -> dict[str, list[int]]:
    """Lista (não conjunto): uma repetição de source_id contaria como duplicado."""
    return {
        "error_log": [int(r[0]) for r in psql(f"SELECT source_id FROM error_logs WHERE host_id={host_id}")],
        "machine_stat": [int(r[0]) for r in psql(f"SELECT source_id FROM machine_stats WHERE host_id={host_id}")],
    }


# --------------------------------------------------------------------------- preparação

def preparar() -> Chaves:
    (ESTADO / "tls").mkdir(parents=True, exist_ok=True)
    chaves = Chaves(*(secrets.token_hex(32) for _ in range(5)), admin=secrets.token_urlsafe(18))
    tls = ESTADO / "tls"
    (tls / "servidor.ext").write_text("subjectAltName=DNS:nginx\nextendedKeyUsage=serverAuth\n")
    for comando in (
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=monitor-e2e CA",
         "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign",
         "-keyout", "ca.key", "-out", "ca.crt"],
        ["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=nginx", "-keyout", "servidor.key",
         "-out", "servidor.csr"],
        ["openssl", "x509", "-req", "-in", "servidor.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial",
         "-days", "1", "-extfile", "servidor.ext", "-out", "servidor.crt"],
    ):
        subprocess.run(comando, cwd=tls, check=True, capture_output=True)
    for ficheiro in ("ca.crt", "servidor.crt", "servidor.key"):
        (tls / ficheiro).chmod(0o644)  # lidos pelo nginx e pelo remote (utilizador 65532); são de teste
    (ESTADO / "central.env").write_text(f"""POSTGRES_USER=monitor
POSTGRES_PASSWORD=e2e
POSTGRES_DB=monitor
POSTGRES_SSLMODE=disable
APP_ENV=development
COOKIE_SECURE=false
LOG_FORMAT=json
LOG_LEVEL=info
HOST_API_KEY_SECRET={chaves.segredo}
ADMIN_EMAIL=admin@e2e.local
ADMIN_PASSWORD={chaves.admin}
ADMIN_NAME=E2E
SMTP_HOST=127.0.0.1
SMTP_PORT=2525
SMTP_USER=e2e
SMTP_PASS=e2e
SMTP_FROM=e2e@monitor.local
""")
    return chaves


def provisionar() -> dict[str, int]:
    """Dois hosts: o principal e um cuja chave foi regenerada (o remote-intruso fica com a antiga)."""
    def host(nome: str, digest: str) -> str:
        return (f"INSERT INTO hosts(name,hostname,api_key_digest,api_key_masked,status) "
                f"VALUES('{nome}','{nome}.e2e.local','{digest}','e2e','offline') RETURNING id")
    ids = {"principal": int(psql(host("e2e-principal", CHAVES.digest(CHAVES.principal)))[0][0])}
    ids["revogado"] = int(psql(host("e2e-revogado", CHAVES.digest(CHAVES.revogada)))[0][0])
    # A revogação é o que RegenerateAPIKey faz: um digest novo na mesma linha (repositories/hosts.go).
    psql(f"UPDATE hosts SET api_key_digest='{CHAVES.digest(CHAVES.substituta)}' WHERE id={ids['revogado']}")
    return ids


def arrancar() -> dict[str, int]:
    compose("--profile", "aplicacao", "--profile", "se1", "build")
    compose("up", "-d", "--wait", "nginx")
    hosts = provisionar()
    compose("up", "-d", "remote")
    esperar(lambda: buffer("remote") is not None, 60, "o remote inicializa o buffer")
    return hosts


def versoes() -> dict[str, str]:
    out = {}
    for repo in REPOSITORIOS:
        proc = subprocess.run(["git", "-C", str(RAIZ / repo), "describe", "--always", "--dirty"], capture_output=True,
                              text=True)
        out[repo] = proc.stdout.strip() or "?"
    return out


# --------------------------------------------------------------------------- cenários

def cenario_feliz(hosts: dict[str, int], n: int) -> Cenario:
    c = Cenario("feliz", f"{n} logs do hello-world e as estatísticas do remote chegam ao central",
                limite=f"{n} logs no central; ≥ 1 estatística; estado do buffer reportado")
    antes = central(hosts["principal"])["logs"]
    gerar_logs("hello-world", n)
    inicio = time.monotonic()
    esperar(lambda: central(hosts["principal"])["logs"] - antes >= n and buffer("remote")["logs_pendentes"] == 0, 120,
            "os logs chegam ao central")
    c.medido = {"entrega_s": round(time.monotonic() - inicio, 2), **central(hosts["principal"])}
    estado = psql(f"SELECT COUNT(*) FROM host_buffer_status WHERE host_id={hosts['principal']}")[0][0]
    c.medido["estado_do_buffer_reportado"] = estado == "1"
    c.passa = c.medido["logs"] - antes == n and c.medido["estatisticas"] >= 1 and c.medido["estado_do_buffer_reportado"]
    return c


def cenario_av1(hosts: dict[str, int], n: int, paragem: float) -> Cenario:
    c = Cenario("AV1", f"central morto (SIGKILL) {paragem:.0f} s; {n} logs gerados durante a falha",
                limite="0 perdidos, 0 duplicados, 0 pendentes de logs, 0 em quarentena")
    host = hosts["principal"]
    logs_antes = buffer("remote")["logs"]
    compose("kill", "backend")
    inicio_falha = time.monotonic()
    gerar_logs("hello-world", n)
    time.sleep(max(0.0, paragem - (time.monotonic() - inicio_falha)))  # a duração da falha é o estímulo
    durante = buffer("remote")
    compose("up", "-d", "--wait", "--no-recreate", "backend")
    volta = time.monotonic()
    recuperacao = esperar(lambda: (lambda b: b["logs_pendentes"] == 0 and b["estatisticas_pendentes"] <= 1)(buffer("remote")),
                          paragem + 600, "o remote entrega o que acumulou")
    compose("stop", "remote")  # estado estável para comparar os dois lados
    try:
        depois = buffer("remote", a_correr=False)
        entregues, no_buffer, no_central = ids_entregues("remote"), ids_no_buffer("remote"), ids_no_central(host)
    finally:
        compose("up", "-d", "remote")
    medido: dict = {
        "paragem_s": round(volta - inicio_falha, 1),
        "logs_gerados_no_buffer": depois["logs"] - logs_antes,
        "pendentes_no_regresso": {"logs": durante["logs_pendentes"], "estatisticas": durante["estatisticas_pendentes"]},
        "recuperacao_s": round(recuperacao, 1),
        "pendentes_no_fim": {"logs": depois["logs_pendentes"], "estatisticas": depois["estatisticas_pendentes"]},
        "quarentena": depois["quarentena"],
    }
    for tipo in ("error_log", "machine_stat"):
        central_ids = no_central[tipo]
        medido[tipo] = {
            "entregues_pelo_remote": len(entregues[tipo]),
            "no_central": len(central_ids),
            "perdidos": len(entregues[tipo] - set(central_ids)),
            "duplicados": len(central_ids) - len(set(central_ids)),
            "sem_origem_no_buffer": len(set(central_ids) - no_buffer[tipo]),
        }
    c.medido = medido
    c.passa = (medido["logs_gerados_no_buffer"] == n and medido["pendentes_no_regresso"]["logs"] >= n
               and depois["logs_pendentes"] == 0 and depois["quarentena"] == 0
               and all(medido[t]["perdidos"] == 0 and medido[t]["duplicados"] == 0 and medido[t]["sem_origem_no_buffer"] == 0
                       for t in ("error_log", "machine_stat")))
    return c


def cenario_mn1(hosts: dict[str, int]) -> Cenario:
    c = Cenario("MN1", "um registo pendente corrompido no buffer fica em quarentena e o central vê-o",
                limite=f"≤ 1 ciclo de recolha ({INTERVALO_ESTATISTICAS:.0f} s + {AMOSTRAGEM_CPU:.0f} s de amostragem do CPU)"
                       f" + {MARGEM_OBSERVACAO:.0f} s de observação")
    host = hosts["principal"]
    antes_central = central(host)["logs"]
    compose("stop", "remote")
    gerar_logs("hello-world", NIVEIS)
    # Metadados que já não são JSON: o remote recusa-se a enviá-los e põe o registo de parte
    # (como em monitor-remote/internal/sender/sender_test.go).
    sqlite("remote", "UPDATE error_logs SET metadata='not JSON' WHERE id=(SELECT MAX(id) FROM error_logs)", a_correr=False)
    compose("up", "-d", "remote")
    esperar(lambda: buffer("remote")["quarentena"] >= 1, 60, "o remote põe o registo em quarentena")
    no_remote = time.monotonic()
    esperar(lambda: central(host)["quarentena"] >= 1, 60, "o central mostra a quarentena")
    atraso = time.monotonic() - no_remote
    esperar(lambda: central(host)["logs"] - antes_central >= NIVEIS - 1, 60, "os outros logs chegam")
    c.medido = {"atraso_s": round(atraso, 2), "quarentena_no_central": central(host)["quarentena"],
                "outros_logs_entregues": central(host)["logs"] - antes_central}
    c.passa = atraso <= INTERVALO_ESTATISTICAS + AMOSTRAGEM_CPU + MARGEM_OBSERVACAO and c.medido["outros_logs_entregues"] == NIVEIS - 1
    return c


def cenario_se1(hosts: dict[str, int], caso: str, chave: str, n: int) -> Cenario:
    c = Cenario(f"SE1-{caso}", f"remote com uma chave {caso}: {n} logs no buffer",
                limite="UNAUTHENTICATED e pausa; 0 linhas no central; registos intactos e pendentes no buffer")
    compose("--profile", "se1", "rm", "-sf", "remote-intruso", chave_intruso=chave)
    subprocess.run(["docker", "volume", "rm", "-f", "monitor-e2e_buffer-intruso"], check=True, capture_output=True)
    compose("--profile", "se1", "up", "-d", "remote-intruso", chave_intruso=chave)
    esperar(lambda: buffer("remote-intruso") is not None, 60, "o remote-intruso inicializa o buffer")
    gerar_logs("hello-world-intruso", n)
    mensagem = "delivery paused: central returned Unauthenticated"
    pausa = esperar(lambda: mensagem in compose("logs", "--no-color", "remote-intruso", chave_intruso=chave), 60,
                    "o remote-intruso pausa por UNAUTHENTICATED", intervalo=0.5)
    estado = buffer("remote-intruso")
    compose("stop", "remote-intruso", chave_intruso=chave)
    outros = psql(f"""SELECT
 (SELECT COUNT(*) FROM error_logs WHERE host_id<>{hosts['principal']}),
 (SELECT COUNT(*) FROM machine_stats WHERE host_id<>{hosts['principal']}),
 (SELECT COUNT(*) FROM host_buffer_status WHERE host_id<>{hosts['principal']}),
 (SELECT COUNT(*) FROM hosts WHERE id={hosts['revogado']} AND last_seen_at IS NOT NULL)""")[0]
    c.medido = {
        "pausa_s": round(pausa, 1),
        "linhas_no_central": dict(zip(["logs", "estatisticas", "estado_do_buffer", "host_revogado_visto"], map(int, outros))),
        "buffer": estado,
    }
    c.passa = (all(int(v) == 0 for v in outros) and estado["logs"] == n and estado["logs_pendentes"] == n
               and estado["logs_enviados"] == 0 and estado["estatisticas_enviadas"] == 0 and estado["quarentena"] == 0)
    return c


# --------------------------------------------------------------------------- principal

def correr(args) -> int:
    resultado = {"data": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "versoes": versoes(),
                 "parametros": {"n": args.n, "paragem_s": args.paragem}, "cenarios": []}
    RESULTADOS.mkdir(exist_ok=True)
    saida = RESULTADOS / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    codigo = 0
    try:
        try:
            inicio = time.monotonic()
            hosts = arrancar()
            resultado["arranque_s"] = round(time.monotonic() - inicio, 1)
        except (RuntimeError, Falha, subprocess.CalledProcessError) as erro:
            resultado["erro"] = f"o sistema não arrancou: {erro}"
            codigo = 2
            return codigo
        execucoes = [
            ("feliz", lambda: cenario_feliz(hosts, args.n)),
            ("AV1", lambda: cenario_av1(hosts, args.n, args.paragem)),
            ("MN1", lambda: cenario_mn1(hosts)),
            ("SE1-inválida", lambda: cenario_se1(hosts, "inválida", CHAVES.invalida, 2 * NIVEIS)),
            ("SE1-revogada", lambda: cenario_se1(hosts, "revogada", CHAVES.revogada, 2 * NIVEIS)),
        ]
        for nome, executar in execucoes:
            try:
                cenario = executar()
            except (Falha, RuntimeError) as erro:
                cenario = Cenario(nome, "não terminou", erro=str(erro))
            resultado["cenarios"].append(cenario.__dict__)
            estado = "PASSA" if cenario.passa else "FALHA"
            print(f"{estado:5}  {cenario.id:14} {json.dumps(cenario.medido, ensure_ascii=False)}"
                  + (f"  erro: {cenario.erro}" if cenario.erro else ""), flush=True)
            if not cenario.passa:
                codigo = 1
        return codigo
    finally:
        if codigo:
            pasta = saida.with_suffix("")
            pasta.mkdir(exist_ok=True)
            for servico in ("backend", "nginx", "remote", "remote-intruso"):
                (pasta / f"{servico}.log").write_text(compose("logs", "--no-color", servico, verificar=False))
        resultado["passa"] = codigo == 0
        saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n")
        print(f"resultado: {saida.relative_to(RAIZ)}")
        if not args.manter:
            compose("--profile", "aplicacao", "--profile", "se1", "down", "-v", "--remove-orphans", verificar=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=500, help=f"logs por cenário (múltiplo de {NIVEIS}; por omissão 500)")
    ap.add_argument("--paragem", type=float, default=60, help="segundos com o central em baixo em AV1 (por omissão 60)")
    ap.add_argument("--manter", action="store_true", help="não desligar o Compose no fim")
    args = ap.parse_args()
    if args.n <= 0 or args.n % NIVEIS or args.n > 1000 * NIVEIS:
        ap.error(f"--n tem de ser múltiplo de {NIVEIS}, entre {NIVEIS} e {1000 * NIVEIS}")
    global CHAVES
    CHAVES = preparar()
    sys.exit(correr(args))


CHAVES: Chaves

if __name__ == "__main__":
    main()
