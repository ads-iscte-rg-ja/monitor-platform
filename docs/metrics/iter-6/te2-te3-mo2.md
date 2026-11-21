# TE2, TE3 e MO2 (Passo 7: D14, ADR-0014; D12, ADR-0015)

Medido a 21/11/2026, antes (`main`: central d21e9c6, remote 12f5767, SDK 69278c7, hello-world 17b42dc) e depois
(alterações do Passo 7, por commitar). Go 1.27.4.

## TE2: *handlers* testáveis em isolamento

```
cd monitor-central && go test -cover ./internal/handlers/
```

| | Antes | Depois | Alvo |
|---|---|---|---|
| Cobertura de `internal/handlers` | 9,5 % | **95,6 %** | ≥ 60 % |
| Ficheiros de teste dos *handlers* | 2 (*login*, `/health`) | 9 (todos os *handlers*) | — |
| Dependências concretas de serviços nos *handlers* | 7 (`*services.X`) + 2 (`*session.SessionManager`) | 0 nos que têm lógica: 7 interfaces mínimas, 1 da sessão de *login* | — |

Os testes usam *fakes* escritos à mão e as páginas reais (`frontend/`), sem base de dados. Correm em ≈ 0,2 s. O
`UserHandler` e o `LegalHandler` guardam ainda o `*session.SessionManager` sem o usar (não muda nada nos testes).

## TE3: lógica temporal sem `time.Sleep`

```
grep -rn "time.Sleep" --include=*_test.go monitor-central monitor-remote monitor-go-sdk monitor-hello-world
```

| | Antes | Depois | Alvo |
|---|---|---|---|
| `time.Sleep` nos testes dos quatro repositórios | 1 (`remote/internal/sender/pause_test.go:289`) | **0** | 0 |
| Resumo diário testado com relógio e fuso controlados | não | sim: 6 casos (antes/às/depois das 9 h, fim do mês, mudança de hora, outro fuso) | — |
| `Europe/Lisbon` escrito no código | 4 (`services/alerts.go` ×2, `services/error_logs.go`, `server/jobs.go`) | 1 (`config.DefaultTimezone`) | — |
| Fuso configurável | não | `APP_TIMEZONE`, validado no arranque | — |

O teste do remote que esperava com `time.Sleep` passa a esperar pelo evento de retoma, registado depois de o
registo ficar marcado como enviado. `time.Now()` em produção: central 16 → 15, remote 14 → 14. As restantes
chamadas carimbam registos ou medem durações, e nenhum teste precisa de as controlar (ADR-0014, alternativas).

## MO2: uma definição por repositório, divergência apanhada por teste

Lista completa dos níveis de log escrita em Go (produção), por repositório:

| Repositório | Antes | Depois | Teste de consistência |
|---|---|---|---|
| central | 5 (`handlers/error_logs.go`, `services/ingestion.go`, `services/error_logs.go`, `services/buffer_status.go`, `alertmetric/errors.go`) | **1** (`models.Levels`) | `CHECK` do `init.sql`; tradução do *protobuf*; SQL das métricas `error_level` e `error_rate` |
| remote | 1 (`validation/records.go`) | **1** (`validation.Levels`) | os 2 `CHECK` de `schema.sql`; tradução para o *protobuf* |
| SDK | 1, não exportada | **1**, exportada (`monitorsdk.Levels`, v0.2.0) | `CHECK` de `schema.sql` do remote |
| hello-world | 1 | **0** (usa o SDK) | — |

As traduções Go ↔ *protobuf* (uma por lado) continuam, de propósito (fronteira do contrato, ADR-0003), mas agora
são verificadas nos dois sentidos. **Prova de que a divergência é apanhada:** retirar `'PANIC'` do `CHECK` do
`init.sql` faz falhar `TestLevelsMatchTheSchema` (central); retirar `LevelPanic` de `monitorsdk.Levels` faz
falhar `TestLevelsMatchTheBufferSchema` (SDK). As duas alterações foram revertidas.

**M7, endereço do central no remote:** 2 validações com regras diferentes → **1** (`validation.CentralURL`), usada
pela configuração e pelo cliente gRPC. Os casos que divergiam (`http://127.0.0.2:3334` aceite só pelo cliente;
`https://central/caminho` aceite só pela configuração) estão no teste `TestCentralURL`.

## Lint e cobertura das linhas novas

| Repositório | Lint antes → depois | Cobertura das linhas novas |
|---|---|---|
| central | 53 → 53 | 90,5 % |
| remote | 20 → 19 | 100 % |
| SDK | 4 → 4 | — (2 funções pequenas, cobertas) |
