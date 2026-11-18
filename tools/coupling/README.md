# Métricas de acoplamento

**Estado:** por implementar (plano §4.1; iteração 0).

Calcula, por pacote, o acoplamento aferente (Ca), eferente (Ce) e a instabilidade
I = Ce / (Ca + Ce) a partir de `go list -deps -json`. Não há uma ferramenta Go mantida para isto,
por isso é um script pequeno. Serve para mostrar a tendência entre iterações; não é um gate.
