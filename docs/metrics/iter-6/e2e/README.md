# E2E (D15, ADR-0012): AV1, SE1 e MN1 ponta a ponta

Gerados por `e2e/correr.py` em 21/11/2026, com o código do D15 por commitar (as versões de cada repositório
estão em cada JSON, campo `versoes`; `-dirty` = com alterações locais). Docker Compose v5.8.0, Go 1.27.4 nas
imagens.

| Ficheiro | Parâmetros | Resultado |
|---|---|---|
| `20261121-091344-antes-da-correcao-mn1.json` | N = 100, paragem 20 s | MN1 **falha**: 10,03 s (2 ciclos). Os outros quatro passam |
| `20261121-091845-n100.json` | N = 100, paragem 20 s, com a correção | 5/5; MN1 5,85 s |
| `20261121-092125-oficial.json` | N = 500, paragem 60 s (por omissão) | 5/5; AV1 0 perdidos, 0 duplicados, recuperação 36,7 s; MN1 0,16 s |

**O defeito de MN1** (histórico do ADR-0010): a fotografia do *buffer* só viaja com estatísticas, e um ciclo de
entrega que acorda antes da recolha não tem nenhuma para enviar. Corrigido no remote: esse ciclo espera pela
recolha seguinte (no máximo um intervalo) e envia-a logo. O atraso de MN1 depende da fase entre a quarentena e a
recolha seguinte: entre 0 e 1 ciclo de recolha (5 s + 1 s de amostragem do CPU).

Como ler um resultado: em cada cenário, `medido` tem os valores observados nos dois lados (PostgreSQL e SQLite),
`limite` o critério e `passa` o veredito. Em AV1, `error_log` e `machine_stat` comparam o *buffer* inteiro com o
central pelo identificador de origem: `perdidos` (entregues pelo remote e ausentes no central), `duplicados`
(repetições no central) e `sem_origem_no_buffer` (no central sem registo correspondente no *buffer*).
