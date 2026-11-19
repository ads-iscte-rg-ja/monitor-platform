#!/usr/bin/env python3
"""Regista N hosts de teste no central e escreve as chaves para o k6.

Escreve o SQL no stdout (para o psql do contentor) e as chaves em dados/hosts.json. As chaves
guardam-se só aqui, em claro, porque são de teste; o central guarda apenas o digest, calculado
como em monitor-central/internal/utils/apikey (HMAC-SHA256 com o prefixo de versão).

O perfil de logs de cada host (plano §4.4, relatório Tabela "Perfil de logs") é atribuído pelo
índice, de forma determinística: em cada 100 hosts, 1 em rajada, 4 ruidosos, 25 normais e 70
silenciosos.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
from pathlib import Path

PREFIXO = b"monitor:host-api-key:v1:"


def perfil(indice: int) -> str:
    resto = indice % 100
    if resto == 0:
        return "rajada"
    if resto <= 4:
        return "ruidoso"
    if resto <= 29:
        return "normal"
    return "silencioso"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hosts", type=int, default=1000)
    ap.add_argument("--segredo", required=True, help="HOST_API_KEY_SECRET do central (64 hex)")
    ap.add_argument("--saida", type=Path, default=Path(__file__).parent / "dados" / "hosts.json")
    args = ap.parse_args()

    segredo = bytes.fromhex(args.segredo)
    if len(segredo) != 32:
        raise SystemExit("o segredo tem de ter 32 bytes (64 hex)")

    hosts, valores = [], []
    for i in range(args.hosts):
        chave = secrets.token_hex(32)
        digest = hmac.new(segredo, PREFIXO + chave.encode(), hashlib.sha256).hexdigest()
        nome = f"carga-{i:05d}"
        hosts.append({"indice": i, "nome": nome, "chave": chave, "perfil": perfil(i)})
        valores.append(f"('{nome}','{nome}.carga.local','{digest}','{chave[:4]}...{chave[-4:]}','offline')")

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(hosts))
    print("BEGIN;")
    print("DELETE FROM hosts WHERE hostname LIKE '%.carga.local';")
    for inicio in range(0, len(valores), 500):
        print("INSERT INTO hosts(name,hostname,api_key_digest,api_key_masked,status) VALUES")
        print(",\n".join(valores[inicio:inicio + 500]) + ";")
    print("COMMIT;")


if __name__ == "__main__":
    main()
