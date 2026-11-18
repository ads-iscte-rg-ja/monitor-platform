package main

// Métricas de acoplamento de Robert C. Martin (Agile Software Development, 2002):
//
//	Ca  acoplamento aferente: pacotes do módulo que importam este pacote
//	Ce  acoplamento eferente: pacotes do módulo que este pacote importa
//	I   instabilidade = Ce / (Ca + Ce)            (0 = estável, 1 = instável)
//	A   abstração     = interfaces / tipos declarados
//	D   distância à sequência principal = |A + I - 1|
//
// Só conta dependências internas ao módulo: as bibliotecas externas não
// mudam com as decisões de desenho do projeto.

import (
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type goPackage struct {
	ImportPath string
	Dir        string
	GoFiles    []string
	Imports    []string
	Module     *struct{ Path string }
}

type couplingMetrics struct {
	pkg                  string
	ca, ce               int
	types, interfaces    int
	instability, abstrac float64
}

func runCoupling(dir string, out io.Writer) error {
	pkgs, err := listPackages(dir)
	if err != nil {
		return err
	}
	if len(pkgs) == 0 {
		return errors.New("nenhum pacote encontrado")
	}
	rows, err := measure(pkgs)
	if err != nil {
		return err
	}
	return writeCSV(out, rows)
}

func measure(pkgs []goPackage) ([]couplingMetrics, error) {
	module := pkgs[0].Module.Path
	ca, ce := couplings(pkgs)
	rows := make([]couplingMetrics, 0, len(pkgs))
	for _, p := range pkgs {
		types, ifaces, err := countTypes(p)
		if err != nil {
			return nil, err
		}
		m := couplingMetrics{
			pkg:        shortName(module, p.ImportPath),
			ca:         ca[p.ImportPath],
			ce:         ce[p.ImportPath],
			types:      types,
			interfaces: ifaces,
		}
		if m.ca+m.ce > 0 {
			m.instability = float64(m.ce) / float64(m.ca+m.ce)
		}
		if types > 0 {
			m.abstrac = float64(ifaces) / float64(types)
		}
		rows = append(rows, m)
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].pkg < rows[j].pkg })
	return rows, nil
}

// couplings devolve Ca e Ce por pacote, contando só importações internas ao módulo.
func couplings(pkgs []goPackage) (ca, ce map[string]int) {
	inModule := make(map[string]bool, len(pkgs))
	for _, p := range pkgs {
		inModule[p.ImportPath] = true
	}
	ca, ce = make(map[string]int), make(map[string]int)
	for _, p := range pkgs {
		for _, imp := range p.Imports {
			if inModule[imp] && imp != p.ImportPath {
				ce[p.ImportPath]++
				ca[imp]++
			}
		}
	}
	return ca, ce
}

func listPackages(dir string) ([]goPackage, error) {
	cmd := exec.Command("go", "list", "-json", "./...")
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GOWORK=off")
	cmd.Stderr = os.Stderr
	raw, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("go list em %s: %w", dir, err)
	}
	var pkgs []goPackage
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	for dec.More() {
		var p goPackage
		if err := dec.Decode(&p); err != nil {
			return nil, err
		}
		if p.Module != nil {
			pkgs = append(pkgs, p)
		}
	}
	return pkgs, nil
}

// countTypes conta os tipos declarados no pacote e quantos são interfaces.
func countTypes(p goPackage) (types, interfaces int, err error) {
	fset := token.NewFileSet()
	for _, name := range p.GoFiles {
		f, err := parser.ParseFile(fset, filepath.Join(p.Dir, name), nil, parser.SkipObjectResolution)
		if err != nil {
			return 0, 0, err
		}
		t, i := countFileTypes(f)
		types += t
		interfaces += i
	}
	return types, interfaces, nil
}

func countFileTypes(f *ast.File) (types, interfaces int) {
	for _, decl := range f.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.TYPE {
			continue
		}
		for _, spec := range gen.Specs {
			types++
			if _, ok := spec.(*ast.TypeSpec).Type.(*ast.InterfaceType); ok {
				interfaces++
			}
		}
	}
	return types, interfaces
}

func shortName(module, path string) string {
	if path == module {
		return "."
	}
	return strings.TrimPrefix(path, module+"/")
}

func writeCSV(out io.Writer, rows []couplingMetrics) error {
	w := csv.NewWriter(out)
	_ = w.Write([]string{"package", "ca", "ce", "instability", "types", "interfaces", "abstractness", "distance"})
	for _, m := range rows {
		// Um pacote sem dependências internas (Ca = Ce = 0) não tem I nem D definidos.
		inst, dist := "", ""
		if m.ca+m.ce > 0 {
			d := m.abstrac + m.instability - 1
			if d < 0 {
				d = -d
			}
			inst = strconv.FormatFloat(m.instability, 'f', 2, 64)
			dist = strconv.FormatFloat(d, 'f', 2, 64)
		}
		_ = w.Write([]string{
			m.pkg,
			strconv.Itoa(m.ca),
			strconv.Itoa(m.ce),
			inst,
			strconv.Itoa(m.types),
			strconv.Itoa(m.interfaces),
			strconv.FormatFloat(m.abstrac, 'f', 2, 64),
			dist,
		})
	}
	w.Flush()
	return w.Error()
}
