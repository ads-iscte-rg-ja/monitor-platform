# Roteiro até à entrega (20/11 → 9/12/2026)

Ordem de execução do que falta no [plano](PLANO_MELHORIAS.md), passo a passo. Cada passo diz que cenário
fecha, que ADR escreve, o que se implementa, como se prova e o que entra no relatório. Atualizar a coluna
**Estado** do quadro à medida que se avança.

**Já feito:** D1–D8, D10–D19 (ADR-0001 a 0016; iterações 1–6 medidas). Cenários com prova: SC1, SC2, SC5,
SC3 (coordenação cumprida; débito não, com diagnóstico), TE1–TE3, AV1–AV4, MO1, MO2, MN1, MN2, SE1–SE3.
Ainda sem prova: SC4 (Passo 9), MO3 e IO1 (Passo 10).

**21/11:** chegaram os slides 07 (documentação, conformidade, testes, variabilidade) e 08 (estilos, falácias da
computação distribuída, conascência). Não invalidam nenhuma decisão; acrescentam o Passo 10 (D20 no
[plano](PLANO_MELHORIAS.md), ADR-0019) e a revisão de D1, E3 e §9 do plano.

## Quadro

| Passo | Datas | Decisão | Cenários que prova | ADR | Repos | Estado |
|---|---|---|---|---|---|---|
| 0 | 20/11 | *Merge* do D8 | SC3 | 0007 | central, platform | feito |
| 1 | 20–22/11 | D13 Strategy nos alertas | MO1 (preparação), US1 | 0008 | central, platform (lint) | feito |
| 2 | 23–24/11 | D19 limite do *buffer* | AV4 | 0009 | remote | feito |
| 3 | 25–27/11 | D17 estado do *buffer* + `/health` live/ready + **medição de MO1** | MO1, MN1, MN2 | 0010 | api, remote, central | feito |
| 4 | 28/11 | D16 retoma sem reinício | AV3 | 0011 | remote | feito |
| 5 | 29/11–1/12 | D15 higiene + E2E | **AV1**, SE1, MN1 (ponta a ponta) | 0012 | todos + `e2e/` | feito |
| 6 | 2/12 | D7 *probes* escaláveis (medir primeiro) | AV2 | 0013 | central | feito |
| 7 | 3/12 | D14 testabilidade + D12 fonte única | TE2, TE3, MO2 | 0014, 0015 | central, remote, sdk | feito |
| 8 | 4/12 | D18 endurecimento (ASVS N1) | SE2, SE3 | 0016 | central | feito |
| 9 | 5/12 | D9 particionamento: medir SC4 e decidir | SC4 | 0017 | central | feito (não se particiona) |
| 10 | 6/12 | D20 estilo, falácias e conascência; vistas finais e de qualidade; conformidade (slides 07–08) | MO3, IO1 | 0019 (+ 0018, 0020–0023 retroativos) | platform, central, remote (comentários `// Package`) | feito, por commitar |
| 11 | 7/12 | Medição final + fecho do relatório | todos | — | platform | |
| 12 | 8/12 | Revisão final | — | — | platform | |
| — | 9/12 | **Entrega** | | | | |

A ordem segue as dependências: D13 cria o mecanismo que MO1 mede; D19 produz os contadores de descarte que
D17 reporta; D17 traz o dado (quarentena) que dá a métrica nova de MO1; o E2E de D15 usa D16 e D17. Os passos
6–9 são independentes entre si.

## Definição de "feito" (vale para todos os passos)

1. **ADR antes do código**, com o modelo `adr/0000-modelo.md`: contexto com números, decisão, teoria (táticas e
   padrões com o slide), alternativas rejeitadas, consequências, verificação. Linha no `adr/README.md` e no
   anexo B do relatório.
2. **Código e testes**, com as mesmas verificações do CI antes do PR: `gofmt -l .`, `go mod tidy -diff`,
   `go vet`, testes com `-race`, integração com PostgreSQL (central), `golangci-lint` com a configuração
   partilhada (o número de *issues* não pode subir), `govulncheck`.
3. **Cobertura do código novo ≥ 80 %** (*quality gate* do SonarQube Cloud), estimada localmente antes do PR,
   incluindo ramos de erro e código de arranque.
4. **Prova do cenário**: teste automático ou medição, com o resultado em `docs/metrics/<iteração>/`.
5. **Plano**: linha "Estado (data)" na decisão.
6. **Relatório**: cap. 6 com Problema / Decisão / Teoria / O que ficou de fora / Alternativas / *Trade-offs* /
   Verificação; cap. 7 com o resultado medido. O relatório compila sem erros, referências indefinidas nem
   *overfull boxes*.
7. **PR por repositório**, CI e Sonar verdes, *merge*. Se mudar o *workflow* ou o lint: mover a tag `v1` do
   `monitor-platform`. Se mudar o contrato: tag nova no `monitor-api` (só alterações aditivas, verificadas pelo
   `buf breaking`).
8. **Decisões não implementadas** também contam: ADR com a medição que as dispensa e o gatilho que as
   tornaria necessárias (como a justiça por host em ADR-0006 e as escritas na BD em E9).

## Passos

### Passo 0: *merge* do D8 (20/11)
* PR do `monitor-central` e do `monitor-platform`; verificar CI e Sonar na `main`.
* `lint/.golangci.yml` não mudou no D8: a tag `v1` fica onde está.

### Passo 1: D13, alertas como Strategy + registo (20–22/11)
* **Problema:** adicionar uma métrica toca ≥ 6 sítios em 3 camadas (M4, A4).
* **Antes de mexer:** contar os ficheiros e funções que uma métrica nova hoje exige (linha de base de MO1).
* **Implementação:** interface `Metric` (`Name`, `ValidateThreshold`, `Format`, `Breached`, `ValueSQL`); registo
  `metrics.Lookup` (Simple Factory); a consulta de avaliação continua a ser **uma** consulta, montada a partir
  dos `ValueSQL()` (não desfazer D5). `for_seconds` por regra (por omissão 0, compatível), com migração 5.
* **Testes:** cada métrica existente com o mesmo comportamento de antes (testes de caracterização primeiro);
  integração da consulta montada; `for_seconds` com relógio controlado (sem `sleep`).
* **Relatório:** padrões GoF (Strategy, Simple Factory) com diagrama de classes pequeno; *program to an
  interface*; *Increase Cohesion*.

### Passo 2: D19, limite do *buffer* do remote (23–24/11)
* **Implementação:** `BUFFER_MAX_MB` (512) e `BUFFER_HARD_MAX_MB`; descarte de pendentes INFO, depois WARN, os
  mais antigos primeiro; ERROR/CRITICAL/PANIC só pelo limite rígido, com evento crítico; contadores
  `dropped_by_level` persistidos no SQLite.
* **Prova de AV4:** teste de integração no remote: *buffer* pequeno, rajada de INFO + ERROR com o central em
  baixo; tamanho ≤ limite, 0 ERROR perdidos, descartes contados.

### Passo 3: D17 + medição de MO1 (25–27/11)
* **Contrato:** campo opcional `buffer` nas estatísticas (`pending`, `quarantined`, `oldest_pending_age_s`,
  `delivery_paused`, `size_bytes`, `dropped_by_level`); `monitor-api` v1.1.0 (aditivo; `buf breaking` verde).
* **Remote:** preenche o campo. **Central:** guarda o último valor por host; mostra-o na API JSON.
* **`/health/live` e `/health/ready`:** *ready* = BD + *heartbeat* de cada *job* que esta instância lidera
  (D8); nginx e Compose passam a usar o *ready*.
* **MO1:** implementar a métrica `buffer_quarantined` com o mecanismo do passo 1, **cronometrada**: registar
  ficheiros Go tocados, migrações e tempo. Alvo: ≤ 3 ficheiros Go + 1 migração, ≤ 1 pessoa-dia.
* **Provas:** MN1 (quarentena visível no central ≤ 1 ciclo, teste de integração); MN2 (*job* bloqueado →
  `/health/ready` 503 em ≤ 2 intervalos).

### Passo 4: D16, o remote retoma sem reinício (28/11)
* Em pausa: 1 tentativa a cada 5 min com o lote mais pequeno; retoma com sucesso. `SIGHUP` recarrega o `.env`.
* **Prova de AV3:** teste com relógio injetado: 403 → sucesso, retoma em ≤ 5 min, sem reiniciar.

### Passo 5: D15, higiene + E2E (29/11–1/12)
* **Higiene:** remover `ErrorLogCollector`; `protectedPaths` derivados das rotas; módulo do SDK na organização;
  `go.work`; LICENSE (MIT) nos repositórios; testes do SDK.
* **E2E em Compose** (`monitor-ws/e2e/` ou `monitor-platform/e2e/`): central + PostgreSQL + remote + hello-world.
  * caminho feliz;
  * **AV1:** parar o central, gerar N registos, voltar a arrancar, verificar N recebidos e 0 duplicados;
  * **SE1:** chave inválida e chave revogada → `UNAUTHENTICATED`, nada gravado;
  * MN1 ponta a ponta.
* *Workflow* noturno (`schedule`) no `monitor-platform`, mais `workflow_dispatch`.
* **Estado (21/11):** feito ([ADR-0012](adr/0012-higiene-e-testes-ponta-a-ponta.md)), em `monitor-platform/e2e/`.
  LICENSE e testes do SDK já vinham da iteração 1; o `go.work` é local (`scripts/go-work.sh`), porque a pasta-mãe
  não é um repositório. O MN1 ponta a ponta encontrou um defeito no remote (fotografia 2 ciclos atrás), corrigido.

### Passo 6: D7, *probes* escaláveis (2/12)
* **Medir primeiro** (como em D6): 1.000 *endpoints* falsos, metade em *timeout*; medir o ciclo atual contra AV2
  (≤ *timeout* + 60 s).
* Se falhar: `next_check_at` com *jitter*, só hosts "devidos", `HEALTH_CONCURRENCY`, *deadline* por ciclo; medir
  de novo. Se cumprir: ADR com a medição e o gatilho; não implementar.
* **Estado (21/11):** a medição falhou (ciclo de 350,7 s, pior atraso 6 min 6 s para um alvo de 60 s);
  implementado ([ADR-0013](adr/0013-probes-de-saude-escalaveis.md)) e medido de novo: cumpre
  (`docs/metrics/iter-6/av2-{antes,depois}.txt`).

### Passo 7: D14 + D12 (3/12)
* **D14:** interfaces mínimas nos *handlers*; `Clock` injetado; `APP_TIMEZONE`. Provas: TE2 (cobertura dos
  *handlers* ≥ 60 %), TE3 (0 `time.Sleep` em testes de lógica temporal).
* **D12:** `models.Level` + teste que compara as constantes Go com o `CHECK` SQL; constantes no SDK; uma só
  `IsLoopbackURL`. Prova de MO2: uma definição por repositório; divergência apanhada por teste.
* **Estado (21/11):** feito ([ADR-0014](adr/0014-handlers-testaveis-relogio-e-fuso.md),
  [ADR-0015](adr/0015-fonte-unica-das-regras-de-dominio.md); `docs/metrics/iter-6/te2-te3-mo2.md`). TE2 9,5 % → 95,6 %;
  TE3 1 → 0 `time.Sleep`; MO2 central 5 → 1 listas de níveis, com 6 testes de consistência. O SDK sai em v0.2.0:
  *merge* do SDK e *tag* antes do PR do hello-world (como no ADR-0012).

### Passo 8: D18, endurecimento (4/12)
* Checklist **OWASP ASVS nível 1** como método, com o resultado (cumpre / não se aplica / falha) no ADR.
* *Middleware* de cabeçalhos (CSP em *Report-Only* primeiro, `frame-ancestors 'none'`, `nosniff`,
  `Referrer-Policy`, HSTS com `COOKIE_SECURE`); Tailwind servido localmente; guarda SSRF no `Dialer.Control`
  das *probes* (depois da resolução DNS).
* **Provas:** SE2 e SE3 com testes.
* **Estado (21/11):** feito ([ADR-0016](adr/0016-endurecimento-por-checklist-asvs.md),
  `docs/seguranca/asvs-n1.md`, `docs/metrics/iter-6/se2-se3.md`). ASVS 5.0.0 N1 (70 requisitos): 9 → 3 falhas,
  com risco aceite. CSP em *enforce* por omissão (decisão do utilizador; `CSP_MODE=report-only` disponível),
  verificada num navegador real. Encontrado e corrigido um defeito antigo no seletor de hosts do *dashboard*.

### Passo 9: D9, medir SC4 e decidir (5/12)
* Gerar 30 dias sintéticos de 1.000 hosts; medir o p95 do *dashboard* e a duração da retenção com a ingestão a
  correr. **Feito assim (21/11):** em vez de estender o `seed-demo` (código de produção), a geração ficou no
  `loadtest/` (`historico.py`, medição `dashboard-30d`): 31 dias com o ritmo e o perfil do k6 (~89 M estatísticas,
  ~239 M erros, com os recibos), duas fases sobre os mesmos dados (sem e com retenção, para isolar o efeito
  desta na ingestão) e o p95 de cada página e API do *dashboard*. Medição "antes" em `docs/metrics/iter-6/sc4-antes/`.
* Separar as causas: se o *dashboard* falhar por consultas sem limite temporal (`COUNT(*)`, `DISTINCT` sobre a
  tabela inteira), a correção é a forma da consulta, não o particionamento. Registar no ADR-0017 o crescimento
  sem limite de `telemetry_receipts`.
* **Resultado (21/11):** antes, p95 29–74 s e a ingestão parada; a causa eram quatro consultas sem limite
  temporal. Com o ADR-0017: p95 16–287 ms, ingestão 7,4 ms, retenção 0,33 s por execução. Não se particiona (o
  critério foi fixado no ADR antes da medição). A migração 8 demora 4 min 12 s nos 143 GB e falhava com o
  `statement_timeout` de 30 s (corrigido; `MIGRATE_TIMEOUT`). Falta o relatório (§D9, cap. 7 com
  `carga-sc4.tex`), que entra no Passo 11.
* **Para o Passo 11:** a retenção passou a estar ativa por omissão (a cada minuto). A medição final corre com ela
  ligada, ao contrário das iterações 3–5; dizê-lo no método do cap. 7.
* Se SC4 falhar: particionamento diário com `DROP PARTITION` (migração testada nos testes de integração). Se
  cumprir: ADR com a medição e o gatilho. Em ambos os casos, ligar ao diagnóstico do SC3 (o particionamento
  ajuda a retenção, não as escritas).

### Passo 10: D20, estilo e documentação segundo os slides 07–08 (6/12)
Por ordem de valor (detalhe em D20 e na revisão de D1, no plano):
1. **ADR-0019 (retroativo):** estilo do sistema (distribuído; central em camadas, replicado sobre uma BD
   partilhada; remote em *pipeline*; alertas em microkernel interno), justificado pelos critérios de decisão do
   slide 08; **tabela das 8 falácias** → resposta → ADR; transações distribuídas evitadas com recibos;
   versionamento de contratos; logs distribuídos sem correlação (lacuna, E6).
2. **Relatório, vistas:** vistas da arquitetura **final** (módulos, C&C em diagrama, alocação); **vistas de
   qualidade** de disponibilidade e de segurança; notação declarada (informal com legenda; `.proto` e `depguard`
   como as partes verificáveis por máquina); legenda em todas as figuras; cap. 3 descrito como reconstrução.
3. **Conascência** no §MO2 / D11 / D12 e no cap. 9 (de significado → de nome e tipo; de valores → fonte única).
4. **Conformidade:** parágrafo sobre o `depguard` como *conformance by analysis* e o seu limite (estruturas de
   execução verificadas por SC3 e pelo E2E); comentários `// Package` em `handlers`, `services` e `repositories`
   (camada, dependências permitidas, regra do `depguard`); tabela cenário → nível de teste.
5. **Medir MO3** (alteração de apresentação real a uma página: 0 ficheiros em `services`/`repositories`) e
   **IO1** (o k6 em JavaScript como agente feito só a partir do `.proto`).
6. **Variabilidade:** um parágrafo (*extension point*, configurador, substituição de componentes, SDK como
   *core asset*), sem dizer que é uma linha de produtos.
7. **Cap. 2:** secção curta com estilos, falácias e conascência (08) e notações e conformidade (07).
8. **ADRs retroativos já escritos (21/11):** 0018 (PostgreSQL), 0020 (*store-and-forward*), 0021 (SDK → *buffer*),
   0022 (*outbox*), 0023 (chaves HMAC). O ADR-0019 junta também o monólito em camadas, os *jobs* no processo, Go
   e a interface no servidor. Acrescentar como alternativas, no Histórico dos ADRs existentes: avaliação de
   alertas por *polling* de 15 s em vez de *streaming* (ADR-0008, E5) e sessões no servidor em vez de JWT
   (ADR-0016). Todos entram no anexo B do relatório.

### Passo 11: medição final e fecho do relatório (7/12) — feito (21/11)
* **Feito:** `medir.py iter-7` e `correr.sh` com os 10 cenários (21/11, 18:45–21:42 UTC, rc=0) em
  `docs/metrics/iter-7/`; tabelas com `--antes iter-3`, e SC4 com `--antes iter-6/sc4-antes` (antes do ADR-0017 →
  final). Cap. 7 atualizado para iter-7, tabela-resumo dos 21 cenários (20 cumprem; SC3 em parte), resumo e
  conclusões escritos; dados de carga apagados da máquina (volume do PG, 174 GB).
* **Notas:** com a retenção ligada por omissão, as duas fases do SC4 final correm ambas com retenção
  (`tabelas.py` passou a rotular pelo que correu de facto). `medir.py` passou a escrever decimais com vírgula e
  `---` onde a métrica não se aplica. Falta, para o utilizador: o E2E de 1 h a partir do `main` (`e2e.yml`).
* **Medições finais:** `scripts/medir.py <iter-final>` (código) e `loadtest/correr.sh <iter-final>` com todos os
  cenários (incluindo `capacidade-1..3`); tabelas com `--antes iter-3` (*baseline* → final).
* **Relatório:**
  * cap. 6: D1–D3 (processo), D7, D9, D12–D19 e o resumo dos ADRs;
  * cap. 7: AV1/AV4, MO1, métricas de código antes/depois, **tabela final** cenário → alvo → medido → cumprido;
  * cap. 8: evolução E1–E9 com gatilhos;
  * resumo (rever com os resultados finais).

### Passo 12: revisão final (8/12) — feito (22/11, por commitar)
* **Feito:** CI verde na `main` dos seis repositórios e *quality gate* OK nos quatro com Sonar; relatório compila
  sem avisos de referências nem *overfull*; 0 menções a outros trabalhos; `make dados ITER=iter-7` (o `carga-sc4.tex` do
  relatório estava desatualizado). Teoria: diapositivos 01 aplicados no cap. 2 (normas, engenharia
  quantificável, causas de insucesso), 05 citados no Strategy e nos GoF do cap. 3, bibliografia "aulas 01–08",
  ASVS na bibliografia, "slide" → "diapositivos". **Lacuna fechada:** o *mutation score* prometido no cap. 5
  nunca tinha sido medido; medido agora (gremlins, `services` do central: eficácia 79,6 %,
  `docs/metrics/iter-7/mutacao.md`) e acrescentado ao cap. 7; depois, com testes de limites da ingestão
  no central (`ingestion_limits_test.go`, por commitar), 87,9 %. Números corrigidos contra os dados (SC5 7→5 ms
  na discussão, CPU do central 15→16 % em SC4 também no ADR-0019, retenção 0,33 s→0,2–0,3 s, MO1 7 sítios,
  repositórios medidos e com CI), separadores de milhares e *host* em itálico uniformizados. READMEs: central
  (retenção ligada por omissão, *bulkhead*, esquema 8) e SDK (v0.2.0).
* **E2E de 1 h a partir do `main`:** corrido no GitHub a 22/11 (run 45014597006), todos os cenários passaram
  (`docs/metrics/iter-7/e2e/`). O agendamento noturno também já correu (22/11, run 45016898494, sucesso); as menções a outro trabalho nos ADR-0001/0002 e no plano foram retiradas (22/11).
* **Carga repetida:** todos os cenários correram mais duas vezes (22/11, `docs/metrics/iter-7/repeticao-2` e `-3`,
  sem falhas); `tabelas.py --repeticoes` dá o mínimo–máximo das três execuções nas tabelas. Nenhum veredicto mudou;
  o que mais variou foi a latência do *dashboard* (SC4 métricas de 1 mês 188–652 ms, SC2 44–168 ms). Texto dos
  cap. 0, 7, 9 e 10 atualizado; a ameaça "Medições únicas" passou a "Poucas repetições". A legenda do SC4
  ("antes do ADR-0017") é corrigida à mão depois de `tabelas.py iter-7 --antes iter-6/sc4-antes --repeticoes ...`.
* PT-PT, afirmações (cada número tem fonte: medição, ADR ou estimativa identificada), coerência entre plano,
  ADRs e relatório.
* **Cobertura da teoria:** cada slide (01–08) tem pelo menos uma decisão ou secção que o aplica, com a citação;
  nenhuma referência a padrões ou estilos com o nome errado (por exemplo, E3 é Service-Based, não SOA).
* **O relatório só trata da arquitetura**: nenhuma menção a outros trabalhos sobre o mesmo sistema.
* Compilação limpa; `make dados` com a iteração final; anexos completos.
* Repositórios: CI e Sonar verdes na `main` de todos; README de cada um atualizado.
