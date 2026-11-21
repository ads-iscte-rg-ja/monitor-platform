# Testes ponta a ponta

Decisão: [ADR-0012](../docs/adr/0012-higiene-e-testes-ponta-a-ponta.md) (plano §7, D15).

O sistema inteiro num Compose descartável, construído a partir dos repositórios irmãos (a pasta-mãe tem de ter
`monitor-central`, `monitor-remote`, `monitor-go-sdk` e `monitor-hello-world` ao lado de `monitor-platform`):

```
hello-world (SDK) ──escreve──▶ buffer SQLite ◀── remote ──gRPC/TLS──▶ nginx ──▶ central ──▶ PostgreSQL
```

O remote fala com o central por `https://`, através do balanceador (ADR-0007), como em produção: o
certificado de teste é gerado a cada execução e o remote confia nele por `SSL_CERT_FILE`.

## Correr

Precisa de Docker (com Compose v2), `openssl` e Python 3 (só biblioteca padrão).

```sh
monitor-platform/e2e/correr.py                 # todos os cenários; AV1 com o central em baixo 60 s
monitor-platform/e2e/correr.py --paragem 3600  # AV1 com o central em baixo 1 h (o cenário do plano)
monitor-platform/e2e/correr.py --manter        # deixa o Compose de pé no fim, para inspecionar
```

Demora cerca de 3 min com a paragem por omissão (mais a primeira construção das imagens). O resultado fica em
`resultados/<data>.json` (versões de cada repositório, parâmetros e, por cenário, o medido, o limite e se
passa); se algum cenário falhar, os logs dos serviços ficam ao lado. Código de saída: 0 tudo passa, 1 algum
cenário falha, 2 o sistema não arrancou. No GitHub corre todas as noites e à mão (`.github/workflows/e2e.yml`).

## Cenários

O condutor (`correr.py`) verifica sempre o estado nos dois lados, PostgreSQL do central e SQLite do remote,
e espera por condições com prazo, nunca por tempos fixos.

| Cenário | Estímulo | Passa se |
|---|---|---|
| Caminho feliz | o hello-world regista N logs (por omissão 500) | os N logs e as estatísticas chegam ao central; o estado do *buffer* é reportado |
| **AV1** | `docker compose kill` do central (sem paragem graciosa), com o balanceador vivo; N logs durante a falha; o central volta | os registos entregues pelo remote (logs e estatísticas) estão todos no central, 0 duplicados, 0 no central sem origem no *buffer*, 0 logs pendentes e 0 em quarentena no fim |
| **MN1** | um log pendente é corrompido no *buffer* (metadados que já não são JSON) | o remote põe-no em quarentena e o central mostra `quarantined = 1` em ≤ 1 ciclo de recolha (5 s + 1 s de amostragem do CPU) + 1 s de observação; os outros logs chegam |
| **SE1** (inválida) | um segundo remote com uma chave que não existe | o remote pausa por `UNAUTHENTICATED`; 0 linhas no central de outro host; os registos ficam todos pendentes no *buffer* |
| **SE1** (revogada) | o mesmo, com a chave antiga de um host cuja chave foi regenerada | igual, e o host revogado nunca é visto pelo central |

AV4 (rajada com o central em baixo, limite do *buffer*) não está aqui: prova-se no remote com o limite real e o
tamanho do ficheiro (ADR-0009), sem precisar do resto do sistema.

## Diferenças em relação a produção

* Intervalos curtos no remote (estatísticas a cada 5 s, logs a cada 2 s, em vez de 30 s e 10 s): o E2E prova o
  mecanismo; a cadência de produção está nos testes com relógio injetado (AV3, MN2).
* Os hosts são provisionados diretamente no PostgreSQL, com o mesmo digest HMAC que o central calcula (como
  `loadtest/provisionar.py`); a revogação é a mesma alteração que `RegenerateAPIKey` faz.
* As imagens do remote e do hello-world (`*.Dockerfile`) existem só para este teste: o remote é um agente
  instalado em cada host, não um serviço em contentor.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `correr.py` | condutor: prepara, arranca, provoca as falhas e verifica |
| `compose.yaml` | o sistema; as chaves entram pelo ambiente, a configuração em `.estado/` (gerada) |
| `nginx.conf` | o balanceador do central com TLS na ingestão gRPC |
| `remote.Dockerfile`, `hello-world.Dockerfile` | imagens de teste (CGO para o SQLite) |
