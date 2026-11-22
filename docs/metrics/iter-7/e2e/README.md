# E2E a partir do `main` (iter-7)

`20261122-105331-main-paragem-1h.json`: `e2e.yml` corrido à mão no GitHub Actions (run 45014597006,
`workflow_dispatch`, `paragem=3600`), a 22/11/2026, sobre o `main` de todos os repositórios (versões no próprio
ficheiro; o SDK entra pela v0.2.0 que o hello-world fixa). Todos os cenários passaram: caminho feliz, AV1 com
3.604 s de central em baixo (0 perdidos, 0 duplicados, recuperação em 216 s), MN1 (6,03 s, limite 7 s), SE1 com
chave inválida e revogada (pausa em 1,1 s, nada gravado no central).
