# Relatório de ADS: pdflatex -> bibtex -> pdflatex x2.
#   make                 gera main.pdf
#   make dados ITER=<n>  copia as tabelas geradas em ../docs/metrics/<iter>/ para gerado/
#   make limpar          remove ficheiros auxiliares
SHELL := /bin/bash
NOME = main
METRICAS = ../docs/metrics

$(NOME).pdf: $(NOME).tex preambulo.tex referencias.bib seccoes/*.tex $(wildcard gerado/*)
	pdflatex -interaction=nonstopmode -halt-on-error $(NOME)
	-bibtex $(NOME)
	pdflatex -interaction=nonstopmode -halt-on-error $(NOME)
	pdflatex -interaction=nonstopmode -halt-on-error $(NOME)

dados:
	@test -n "$(ITER)" || { echo "uso: make dados ITER=<baseline|iter-N>"; exit 1; }
	mkdir -p gerado
	cp $(METRICAS)/$(ITER)/*.tex gerado/ 2>/dev/null || true
	cp $(METRICAS)/$(ITER)/*.csv gerado/ 2>/dev/null || true

limpar:
	rm -f $(NOME).{aux,bbl,blg,log,out,toc,lof,lot} seccoes/*.aux

.PHONY: dados limpar
