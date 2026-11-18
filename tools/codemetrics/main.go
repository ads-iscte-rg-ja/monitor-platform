// Command codemetrics mede um módulo Go para o relatório de ADS.
//
//	-mode coupling   por pacote: Ca, Ce, instabilidade, abstração, distância (Martin, 2002)
//	-mode functions  por função: linhas e complexidade ciclomática (McCabe, 1976)
//
// Os ficheiros de teste ficam de fora: medem-se as decisões de desenho do
// código de produção. A complexidade cognitiva vem do gocognit
// (golangci-lint), que o scripts/medir.py junta a esta saída.
//
// Uso: go run . -mode coupling -dir ../../../monitor-central > acoplamento.csv
package main

import (
	"flag"
	"fmt"
	"os"
)

func main() {
	dir := flag.String("dir", ".", "raiz do módulo Go a medir")
	mode := flag.String("mode", "coupling", "coupling | functions")
	flag.Parse()

	var err error
	switch *mode {
	case "coupling":
		err = runCoupling(*dir, os.Stdout)
	case "functions":
		err = runFunctions(*dir, os.Stdout)
	default:
		err = fmt.Errorf("modo desconhecido %q", *mode)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "codemetrics:", err)
		os.Exit(1)
	}
}
