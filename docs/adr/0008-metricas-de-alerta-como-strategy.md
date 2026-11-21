# ADR-0008: Métricas de alerta como Strategy, com um registo como Simple Factory

* **Estado:** Aceite
* **Data:** 2026-11-20
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Modifiability
* **Cenários relacionados:** MO1; lacunas M4, A4
* **Decisão do plano:** D13 (`../PLANO_MELHORIAS.md` §7.3)

## Contexto
MO1 pede que uma métrica de alerta nova se implemente e teste sem tocar no avaliador genérico, com ≤ 3
ficheiros Go + 1 migração e ≤ 1 pessoa-dia. Hoje, o conhecimento sobre cada métrica está espalhado. A linha
de base, contada no código antes desta decisão, é de **7 sítios em 5 ficheiros e 3 camadas**:

| Camada | Ficheiro | O que muda por métrica |
|---|---|---|
| Serviço | `services/alerts.go` | lista de métricas válidas; regra do limiar; formatação do valor; caso especial da comparação (`error_level` usa ≥) |
| Repositório | `repositories/alerts.go` | ramo do `CASE` que calcula o valor; condição que decide se o valor é recente |
| Apresentação | `handlers/alerts.go`, `partials/alert-fields.html` | lista do formulário; texto de ajuda |
| Base de dados | migração | `CHECK (metric IN (…))` |

Cada métrica nova obriga a mexer no avaliador (o `switch` do serviço e o `CASE` da consulta). É baixa coesão:
o que pertence a uma métrica está em sete sítios, e cada um tem de ser encontrado.

## Decisão
1. **Interface `alertmetric.Metric`** com o comportamento que varia por métrica: `Name`, `Help`,
   `ValidThreshold`, `Breached`, `Format`, `FormatThreshold` e `Query`. Cada métrica é uma estratégia
   concreta, no seu ficheiro.
2. **Registo** (`alertmetric.Lookup`, `All`, `Names`): cada métrica regista-se no `init` do seu ficheiro, e o
   resto do central obtém-na pelo nome (Simple Factory). O serviço valida, compara e formata através da
   interface; o *handler* gera a lista e a ajuda do formulário a partir do registo.
3. **Uma consulta por métrica, constante.** Cada métrica fornece a consulta completa que devolve as suas regras
   com o valor atual, montada em tempo de compilação a partir de blocos constantes partilhados. A avaliação faz
   uma consulta por métrica registada (6), qualquer que seja o número de regras: continua *set-based* (ADR-0005).
   Nenhum SQL é montado em tempo de execução.
4. **O `CHECK` da base de dados mantém-se**, como defesa em profundidade, e um teste de integração compara-o com
   o registo: uma métrica nova sem migração é apanhada pelos testes.
5. **Fica de fora a duração sustentada** (`for_seconds`, cenário US1, prioridade M,L): exige guardar o início de
   cada violação e mudar o formulário. Gatilho: alertas falsos por picos isolados reportados pelos utilizadores.

## Fundamentação teórica
* **GoF Strategy** (slide 05): a família de algoritmos (calcular, validar, comparar e formatar uma métrica)
  fica encapsulada atrás de uma interface e é intercambiável; o avaliador depende da abstração.
* **Simple Factory** (slide 05): o registo cria e devolve a estratégia pelo nome que vem da base de dados.
* ***Program to an interface, not an implementation***; Modifiability → ***Increase Cohesion***
  (o que muda junto fica junto) e ***Reduce Coupling*** (o avaliador não conhece as métricas).
* **Open/Closed**: o avaliador fica fechado a alterações e aberto a métricas novas.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Um fragmento SQL por métrica, juntado num único `CASE` em tempo de execução | SQL montado em tempo de execução (Sonar S2077); a consulta por métrica dá o mesmo com SQL constante |
| Calcular os valores em Go, com uma consulta por regra | N × M consultas, contra ADR-0005 |
| Uma consulta única com todos os valores possíveis para cada host | Uma métrica que precise de um dado novo obrigaria a mudar a consulta partilhada: volta a tocar no avaliador |
| Motor de regras configurável na base de dados | O custo do mecanismo é muito maior do que o ritmo de mudança (slide 03: só se abstrai o que muda) |

## Consequências
* **Positivas:** uma métrica nova é um ficheiro novo mais uma migração; o avaliador, o serviço e o formulário
  não mudam. Cada métrica testa-se isoladamente.
* **Negativas / *trade-offs*:**
  * A estratégia conhece o SQL do seu valor: há SQL fora da camada de repositórios. É o preço de MO1 (a
    alternativa separaria o que muda junto); fica confinado ao pacote `alertmetric`, com regra de camadas no lint.
  * 6 consultas por ciclo de avaliação em vez de 1. Cada uma é *set-based*; a 15 s por ciclo, o custo é
    irrelevante face à ingestão.

## Verificação
* Teste de caracterização (integração) escrito **antes** da refatoração: o valor de cada uma das 6 métricas e
  as regras avaliadas (estatísticas antigas e regras desativadas ficam de fora). Passa antes e depois.
* Testes unitários de cada estratégia; teste de consistência registo ↔ `CHECK`.
* MO1 medido em D17: implementar a métrica `buffer_quarantined` e registar ficheiros tocados e tempo.

## Histórico
* 2026-11-21 (alternativa que já estava no plano, §9 e E5, e faltava aqui): **avaliar os alertas à entrada dos
  dados** (*streaming*, padrão Observer), em vez de a cada 15 s. Rejeitada nesta decisão: o *polling* cumpre AV2
  (o atraso até ao alerta inclui um ciclo de 15 s e fica em 50,4 s, contra 60 s; ADR-0013) e mantém as
  estratégias sem estado por regra, que é o que torna MO1 barato. **Gatilho (E5):** um ciclo de avaliação acima
  de 5 s. O ADR-0019 descreve o registo de estratégias como o microkernel interno do central.
