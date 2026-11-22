# Mutation testing: `monitor-central/internal/services` (iter-7)

Métrica de tendência da Tabela GQM ("Os testes detetam faltas?"), medida numa amostra, como previsto no
relatório (cap. 5). Sem alvo: serve para saber se a cobertura corresponde a verificação.

## Como se mediu (22/11/2026)

* Código: `monitor-central` em `ed445f1` (`main`, versão final).
* Ferramenta: gremlins v0.6.0 (`go install github.com/go-gremlins/gremlins/cmd/gremlins@v0.6.0`), Go 1.27.4.
* Numa cópia descartável do repositório, na raiz do módulo:

  ```sh
  GOWORK=off gremlins unleash --workers 8 --timeout-coefficient 10 \
    --output mutacao.json ./internal/services
  ```

* Só os testes unitários do pacote (sem PostgreSQL); 54 s.
* Dados brutos: `dados/monitor-central-mutacao-services.json`.

## Resultado

| Medida | Valor |
| --- | --- |
| Mutantes cobertos (mortos + sobreviventes) | 265 |
| Mortos | 211 |
| Sobreviventes | 54 |
| Não cobertos pelos testes | 29 |
| Em *timeout* (fora da eficácia) | 3 |
| **Eficácia dos testes** (mortos / (mortos + sobreviventes)) | **79,6 %** |
| Cobertura dos mutantes | 90,1 % |

Mutadores aplicados: negação de condições 205, limites de condições 64, aritmética 24, sinais 3, incremento 1.

## Onde sobrevivem

| Ficheiro | Sobreviventes | Não cobertos |
| --- | ---: | ---: |
| `ingestion.go` | 23 | 0 |
| `alerts.go` | 13 | 8 |
| `hosts.go` | 9 | 0 |
| `host_health.go` | 6 | 1 (+3 *timeout*) |
| `buffer_status.go` | 1 | 8 |
| `auth.go` | 1 | 7 |
| `user.go` | 0 | 5 |
| `error_logs.go` | 1 | 0 |

Os 23 de `ingestion.go` são quase todos **limites**: `>` trocado por `>=` (e vice-versa) nas validações de
tamanho (mensagem 16 384, *stack trace* 65 536, metadados 32 768, aplicação 200, ambiente 100, chave 256) e
de intervalo (CPU 0–100, RAM e disco usados ≤ total). Os testes verificam que um valor muito acima do limite é
recusado e que um valor normal passa, mas nenhum fixa o valor exato do limite. É a lacuna típica que a
cobertura não mostra: as linhas estão 100 % cobertas e o limite exato não está verificado. Não se conhece nenhum
defeito associado, mas um teste de tabela com `limite` e `limite + 1` por campo mataria quase todos.

## Depois: testes de limites da ingestão (22/11/2026)

Acrescentou-se `internal/services/ingestion_limits_test.go` ao central (só testes; o código de produção não
mudou): cada limite é testado no valor exato (aceite) e um passo além (recusado), incluindo os inferiores
(CPU 0, usado 0, total 0 com usado 0, `hostID` 0 e 1, identificador de origem 0 e 1, lote de 100 erros).
Mesmo comando, mesmo código de produção; dados em `dados/monitor-central-mutacao-services-depois.json`.

| Medida | Antes | Depois |
| --- | ---: | ---: |
| Mortos | 211 | 233 |
| Sobreviventes | 54 | 32 |
| Sobreviventes em `ingestion.go` | 23 | 1 |
| Não cobertos | 29 | 29 |
| **Eficácia dos testes** | **79,6 %** | **87,9 %** |

O sobrevivente que fica em `ingestion.go` (linha 55, `hostID <= 0` → `hostID < 0` em `IngestStatsBatch`) é
**equivalente**: com `hostID` 0, a validação de cada amostra (`prepareMachineStat`) recusa-o com o mesmo erro,
por isso nenhum teste o pode distinguir. Os 32 restantes estão sobretudo em `alerts.go` (13) e `hosts.go` (9).
Lint do central sem alteração (52).
