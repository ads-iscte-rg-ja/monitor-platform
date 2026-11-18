# codemetrics

Mede um módulo Go para o relatório (plano §4.1). Só código de produção: os testes ficam de fora.

| Modo | Saída (CSV) | Métricas |
|---|---|---|
| `-mode coupling` | uma linha por pacote | Ca, Ce, instabilidade I = Ce/(Ca+Ce), abstração A = interfaces/tipos, distância D = \|A+I−1\| (Martin, 2002) |
| `-mode functions` | uma linha por função | linhas e complexidade ciclomática (McCabe, 1976), contada como no gocyclo |

```sh
go run . -mode coupling  -dir ../../../monitor-central
go run . -mode functions -dir ../../../monitor-remote
```

Normalmente não se corre à mão: o `scripts/medir.py` usa-a e junta-lhe a complexidade cognitiva do gocognit.

**Porque é que existe.** Não há nenhuma ferramenta Go mantida que calcule as métricas de Martin. A ciclomática
de todas as funções também não se consegue tirar do golangci-lint, porque ele só reporta as que passam
o limite. O código é pequeno (~250 linhas, só biblioteca padrão) e passa a configuração de lint partilhada.

**Como ler.** As métricas de acoplamento servem para ver a **tendência** entre iterações; não são um gate.
Pacotes de dados e configuração (`models`, `config`) têm D ≈ 1 por serem estáveis e concretos, e
isso é esperado. Um pacote sem dependências internas (Ca = Ce = 0) fica sem I nem D.
