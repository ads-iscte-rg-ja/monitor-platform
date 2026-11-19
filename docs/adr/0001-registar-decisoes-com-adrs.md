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
* A **decisão** de um ADR aceite não se altera. Uma decisão que muda dá origem a um ADR novo que **substitui** o
  anterior, e o estado do antigo é atualizado. Assim fica o histórico do raciocínio, incluindo as decisões revistas
  (como recomendam a AWS Prescriptive Guidance e o Azure Well-Architected Framework).
* São permitidas **correções** que não mudam a decisão: esclarecer o texto, corrigir um facto ou atualizar uma
  consequência que a experiência confirmou. Cada correção fica registada na secção **Histórico** do próprio ADR,
  com a data, o que mudou e porquê. Na dúvida sobre se é correção ou mudança de decisão, é mudança: ADR novo.
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
* **Negativas:** disciplina extra em cada PR. Mitigação: modelo curto e revisão cruzada sempre que possível.

## Verificação
Cada decisão D1–D19 do plano tem um ADR aceite antes da entrega (9/12/2026).

## Histórico
* **2026-11-19, correção:** a regra de imutabilidade passou a distinguir correções (permitidas e registadas nesta
  secção) de mudanças de decisão (ADR novo). Motivo: o ADR-0002 tinha sido esclarecido depois de aceite sem que a
  regra o previsse; a prática da indústria faz esta distinção.
* **2026-11-19, correção:** a revisão cruzada passou de "obrigatória" a "sempre que possível". Com uma equipa de
  duas pessoas, uma revisão obrigatória bloquearia o trabalho sempre que uma delas não estivesse disponível; a
  proteção do `main` exige CI verde mas 0 aprovações (relatório, §5.3). A decisão deste ADR (registar as decisões
  em ADRs) não muda.
