# ADR-0001: Registar as decisões arquiteturais em ADRs no monitor-platform

* **Estado:** Aceite
* **Data:** 2026-11-18
* **QA principal:** Modifiability (manutenção do conhecimento arquitetural)
* **Cenários relacionados:** — (transversal)

## Contexto
O sistema Monitor tem uma arquitetura implícita: há decisões importantes no código (store-and-forward em
SQLite, outbox transacional, HMAC das chaves, jobs dentro do processo), mas nenhuma está escrita com o seu
porquê. Os slides de ADS lembram que *"every software system has a software architecture (not necessarily
known to anyone)"* e que, sem documentação, é *"impossible to evaluate the architecture"*. O projeto é
avaliado precisamente pela fundamentação das decisões, e duas cadeiras (ADS e EUVI) mexem no mesmo código.

## Decisão
* Cada decisão arquitetural fica num ficheiro `docs/adr/NNNN-titulo.md`, com o modelo `0000-modelo.md`.
* Os ADRs são **imutáveis depois de aceites**. Uma decisão que muda dá origem a um ADR novo que **substitui** o
  anterior, e o estado do antigo é atualizado. Assim fica o histórico do raciocínio, incluindo as decisões revistas.
* O ADR escreve-se **antes** do código e faz parte do mesmo PR.
* Também se escrevem **ADRs retroativos** para as decisões que já existem no código.
* O anexo B do relatório reúne os ADRs; o capítulo 6 resume-os.

## Fundamentação teórica
* *Write for the reader* e documentar o que é ensinado a quem chega, o que tem risco e o que muda com frequência (slide 06).
* *"The architecture should be visible & self-evident … make decisions obvious, well communicated & defended"* (slide 06).
* Documentar só o que dá retorno (slide 02): um ADR curto por decisão em vez de documentação exaustiva.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Documento único de arquitetura | Mistura decisões com tempos diferentes; perde o histórico de decisões revistas |
| Documentação UML completa | Custo alto, pouco retorno (YAGNI, slide 06) |
| Decisões só no relatório LaTeX | O relatório é uma entrega; os ADRs continuam a ser usados depois dela |

## Consequências
* **Positivas:** o raciocínio fica rastreável; o relatório reutiliza o texto dos ADRs; as decisões revistas
  (ex.: Prometheus, adiado e depois adotado) mostram adaptação aos requisitos.
* **Negativas:** disciplina extra em cada PR. Mitigação: modelo curto e revisão cruzada obrigatória.

## Verificação
Cada decisão D1–D19 do plano tem um ADR aceite antes da entrega (9/12/2026).
